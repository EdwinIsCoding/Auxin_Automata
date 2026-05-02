"""AI Treasury Agent — autonomous CFO for the hardware wallet.

IMPORTANT CONSTRAINT
--------------------
The treasury agent NEVER signs transactions, transfers funds, or modifies
on-chain state directly.  It analyses and advises.  The bridge acts on
auto_executable recommendations within pre-defined safe bounds (throttle
inference frequency, adjust per-payment lamport amount).  Fund transfers
are never auto-executable.  This boundary is enforced by the action filter
in this module and must not be relaxed.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

# Top-level import so tests can patch auxin_sdk.treasury.agent.anthropic
try:
    import anthropic  # type: ignore[import]
except ImportError:
    anthropic = None  # type: ignore[assignment]

from ..risk.types import RiskReport
from .types import BudgetAllocation, RecommendedAction, TreasuryAnalysis

log = structlog.get_logger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000

# ── Auto-executable action allowlist — fund transfers are never allowed ────────
_AUTO_EXEC_ALLOWLIST = frozenset(["throttle_inference", "increase_reserve"])


def _is_auto_executable_safe(action: str) -> bool:
    """Only throttling and reserve rebalancing are auto-executable."""
    action_lower = action.lower()
    return any(keyword in action_lower for keyword in _AUTO_EXEC_ALLOWLIST)


class TreasuryAgent:
    """
    AI-powered treasury manager for the hardware wallet.

    The agent calls an LLM (Claude or Gemini) to reason about the wallet's
    financial state and returns a TreasuryAnalysis.  On API failure it falls
    back to a deterministic heuristic so the demo never stalls.

    Usage
    -----
    ::

        agent = TreasuryAgent(api_key=os.environ["ANTHROPIC_API_KEY"])
        analysis = await agent.analyze(payment_history, compliance_history,
                                        balance_sol, risk_report)
    """

    PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "treasury_agent_v1.txt"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        analysis_interval_s: int = 120,
    ) -> None:
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GEMINI_API_KEY")
        self._model = model
        self.analysis_interval_s = analysis_interval_s

        # Load prompt from file — log the version for reproducibility
        if self.PROMPT_PATH.exists():
            self._system_prompt = self.PROMPT_PATH.read_text()
            log.info("treasury_agent.prompt_loaded", path=str(self.PROMPT_PATH))
        else:
            log.warning("treasury_agent.prompt_missing", path=str(self.PROMPT_PATH))
            self._system_prompt = "You are a treasury manager. Return valid JSON."

    async def analyze(
        self,
        payment_history: list[dict[str, Any]],
        compliance_history: list[dict[str, Any]],
        balance: float,
        risk_report: RiskReport | None = None,
    ) -> TreasuryAnalysis:
        """
        Analyse the wallet and return a TreasuryAnalysis.

        Falls back to heuristic computation if the LLM API is unavailable.
        The fallback is designed to be production-safe: it always returns a
        valid TreasuryAnalysis and never raises.
        """
        risk_score = risk_report.overall_score if risk_report else None
        context = self._build_context(payment_history, compliance_history, balance, risk_score)

        if not self._api_key:
            log.warning("treasury_agent.no_api_key", fallback=True)
            return self._fallback_analysis(payment_history, balance, risk_score, context)

        try:
            return await self._call_llm(context, balance, risk_score)
        except Exception as exc:
            log.warning("treasury_agent.llm_failed", error=str(exc), fallback=True)
            return self._fallback_analysis(payment_history, balance, risk_score, context)

    # ── LLM call with retries ──────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _call_llm(
        self,
        context: str,
        balance: float,
        risk_score: float | None,
    ) -> TreasuryAnalysis:
        """Call the Claude API and parse the response into TreasuryAnalysis."""
        if anthropic is None:  # pragma: no cover
            raise RuntimeError("anthropic package not installed — run: uv add anthropic")

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        t0 = time.monotonic()
        message = await client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=self._system_prompt,
            messages=[{"role": "user", "content": context}],
        )
        latency_ms = (time.monotonic() - t0) * 1000
        log.info("treasury_agent.llm_ok", latency_ms=round(latency_ms, 1), model=self._model)

        raw_text = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        data = json.loads(raw_text)
        return self._parse_llm_response(data, balance, risk_score)

    def _parse_llm_response(
        self,
        data: dict[str, Any],
        balance: float,
        risk_score: float | None,
    ) -> TreasuryAnalysis:
        """Parse and sanitise the LLM JSON response into a TreasuryAnalysis."""
        actions: list[RecommendedAction] = []
        for act_data in data.get("recommended_actions", []):
            action_str = act_data.get("action", "")
            # Enforce safety: auto_executable only for allowlisted actions
            safe_auto = _is_auto_executable_safe(action_str) and act_data.get("auto_executable", False)
            actions.append(
                RecommendedAction(
                    action=action_str,
                    priority=act_data.get("priority", "medium"),
                    reasoning=act_data.get("reasoning", ""),
                    auto_executable=safe_auto,
                )
            )

        alloc_data = data.get("budget_allocation", {})
        inference = float(alloc_data.get("inference", 70.0))
        reserve = float(alloc_data.get("reserve", 20.0))
        buffer = float(alloc_data.get("buffer", 10.0))
        # Normalise to 100
        total = inference + reserve + buffer
        if total > 0:
            inference = round(inference / total * 100, 1)
            reserve = round(reserve / total * 100, 1)
            buffer = round(100.0 - inference - reserve, 1)

        return TreasuryAnalysis(
            burn_rate_lamports_per_hour=int(data.get("burn_rate_lamports_per_hour", 0)),
            runway_hours=float(data.get("runway_hours", 0.0)),
            runway_status=data.get("runway_status", "healthy"),
            budget_allocation=BudgetAllocation(inference=inference, reserve=reserve, buffer=buffer),
            recommended_actions=actions,
            anomaly_flags=data.get("anomaly_flags", []),
            summary=data.get("summary", ""),
            risk_score_context=risk_score,
            analyzed_at=datetime.now(timezone.utc),
            used_fallback=False,
        )

    # ── Deterministic fallback ─────────────────────────────────────────────────

    def _fallback_analysis(
        self,
        payment_history: list[dict[str, Any]],
        balance: float,
        risk_score: float | None,
        context: str,
    ) -> TreasuryAnalysis:
        """Heuristic treasury analysis used when the LLM API is unavailable."""
        now = datetime.now(timezone.utc)
        last_24h = [
            p for p in payment_history
            if self._parse_ts(p.get("timestamp")) >= now - timedelta(hours=24)
        ]
        total_spent_24h = sum(p.get("lamports", 0) for p in last_24h)
        burn_rate = int(total_spent_24h / 24)

        balance_lamports = balance * LAMPORTS_PER_SOL
        runway_hours = (balance_lamports / burn_rate) if burn_rate > 0 else 9999.0

        if runway_hours < 12:
            runway_status = "critical"
        elif runway_hours < 48:
            runway_status = "warning"
        else:
            runway_status = "healthy"

        actions: list[RecommendedAction] = []
        anomaly_flags: list[str] = []

        if runway_hours < 12:
            actions.append(
                RecommendedAction(
                    action="throttle_inference",
                    priority="critical",
                    reasoning=f"Runway is {runway_hours:.1f}h — throttle to extend life.",
                    auto_executable=True,
                )
            )
            anomaly_flags.append("critical_low_runway")

        if risk_score is not None and risk_score < 50:
            actions.append(
                RecommendedAction(
                    action="increase_reserve",
                    priority="high",
                    reasoning=f"Risk score is {risk_score:.0f} (<50). Increase reserve to 30%.",
                    auto_executable=True,
                )
            )

        # Provider concentration check
        provider_counts: dict[str, int] = {}
        for p in payment_history:
            pk = p.get("provider", "unknown")
            provider_counts[pk] = provider_counts.get(pk, 0) + 1
        total = len(payment_history)
        if total > 0:
            top_provider_pct = max(provider_counts.values()) / total if provider_counts else 0
            if top_provider_pct > 0.70:
                actions.append(
                    RecommendedAction(
                        action="diversify_providers",
                        priority="medium",
                        reasoning=f"Single provider handles {top_provider_pct*100:.0f}% of payments.",
                        auto_executable=False,
                    )
                )

        reserve_pct = 30.0 if (risk_score or 100) < 50 else 20.0
        buffer_pct = 10.0
        inference_pct = round(100.0 - reserve_pct - buffer_pct, 1)

        summary = (
            f"Heuristic analysis (API unavailable). "
            f"Burn rate: {burn_rate:,} lamports/hr. "
            f"Runway: {runway_hours:.1f}h ({runway_status}). "
            f"{'Action required.' if actions else 'No critical issues.'}"
        )

        return TreasuryAnalysis(
            burn_rate_lamports_per_hour=burn_rate,
            runway_hours=round(runway_hours, 1),
            runway_status=runway_status,
            budget_allocation=BudgetAllocation(
                inference=inference_pct,
                reserve=reserve_pct,
                buffer=buffer_pct,
            ),
            recommended_actions=actions,
            anomaly_flags=anomaly_flags,
            summary=summary,
            risk_score_context=risk_score,
            analyzed_at=now,
            used_fallback=True,
        )

    # ── Context builder ────────────────────────────────────────────────────────

    def _build_context(
        self,
        payment_history: list[dict[str, Any]],
        compliance_history: list[dict[str, Any]],
        balance: float,
        risk_score: float | None,
    ) -> str:
        now = datetime.now(timezone.utc)
        last_24h = [
            p for p in payment_history
            if self._parse_ts(p.get("timestamp")) >= now - timedelta(hours=24)
        ]
        last_6h = [
            p for p in payment_history
            if self._parse_ts(p.get("timestamp")) >= now - timedelta(hours=6)
        ]
        total_spent_24h = sum(p.get("lamports", 0) for p in last_24h)
        total_spent_6h = sum(p.get("lamports", 0) for p in last_6h)
        burn_24h = total_spent_24h / 24
        burn_6h = total_spent_6h / 6 if last_6h else 0

        provider_counts: dict[str, int] = {}
        for p in payment_history[-100:]:
            pk = p.get("provider", "unknown")
            provider_counts[pk] = provider_counts.get(pk, 0) + 1

        balance_lamports = balance * LAMPORTS_PER_SOL

        return (
            f"WALLET STATE (as of {now.isoformat()})\n"
            f"Balance: {balance:.6f} SOL ({balance_lamports:.0f} lamports)\n"
            f"Total payments (all history): {len(payment_history)}\n"
            f"Payments (last 24h): {len(last_24h)} totalling {total_spent_24h:,} lamports\n"
            f"Avg burn rate (24h): {burn_24h:.0f} lamports/hr\n"
            f"Avg burn rate (6h): {burn_6h:.0f} lamports/hr\n"
            f"Compliance events (total): {len(compliance_history)}\n"
            f"Provider distribution (last 100 payments): {dict(provider_counts)}\n"
            f"Risk score: {risk_score if risk_score is not None else 'N/A'}\n\n"
            f"Analyse this data and return a JSON TreasuryAnalysis."
        )

    @staticmethod
    def _parse_ts(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

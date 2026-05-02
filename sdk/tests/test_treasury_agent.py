"""Tests for the AI treasury agent."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auxin_sdk.risk.types import RiskBreakdown, RiskReport
from auxin_sdk.treasury.agent import TreasuryAgent, _is_auto_executable_safe
from auxin_sdk.treasury.types import TreasuryAnalysis


def _make_risk_report(score: float = 75.0) -> RiskReport:
    bd = RiskBreakdown(category="Financial Health", score=score, weight=1.0, factors=[])
    return RiskReport(
        overall_score=score,
        grade="B",
        breakdown=[bd],
        trend="stable",
        trend_data=[],
        computed_at=datetime.now(timezone.utc),
    )


def _make_payments(n: int = 50, provider: str = "ProvA") -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {
            "timestamp": (now - timedelta(hours=i)).isoformat(),
            "lamports": 5000,
            "provider": provider,
            "tx_signature": f"sig{i:04d}",
        }
        for i in range(n)
    ]


VALID_LLM_RESPONSE = {
    "burn_rate_lamports_per_hour": 25000,
    "runway_hours": 200.0,
    "runway_status": "healthy",
    "budget_allocation": {"inference": 70.0, "reserve": 20.0, "buffer": 10.0},
    "recommended_actions": [
        {
            "action": "monitor_burn_rate",
            "priority": "low",
            "reasoning": "Burn rate is stable at 25,000 lamports/hr.",
            "auto_executable": False,
        }
    ],
    "anomaly_flags": [],
    "summary": "Wallet is healthy with 200h runway. No action required.",
}


class TestFallbackAnalysis:
    """Fallback heuristic is used when API key is absent or LLM fails."""

    @pytest.mark.asyncio
    async def test_no_api_key_produces_valid_analysis(self):
        agent = TreasuryAgent(api_key=None)
        payments = _make_payments(50)
        result = await agent.analyze(payments, [], balance=1.0)
        assert isinstance(result, TreasuryAnalysis)
        assert result.used_fallback is True
        assert result.burn_rate_lamports_per_hour >= 0
        assert result.runway_status in ("healthy", "warning", "critical")

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self):
        agent = TreasuryAgent(api_key="fake-key")
        with patch.object(agent, "_call_llm", side_effect=Exception("API timeout")):
            result = await agent.analyze(_make_payments(30), [], balance=0.5)
        assert result.used_fallback is True
        assert isinstance(result, TreasuryAnalysis)

    @pytest.mark.asyncio
    async def test_fallback_critical_runway(self):
        """With tiny balance and high burn, fallback should flag critical runway."""
        agent = TreasuryAgent(api_key=None)
        # 50 payments in last 24h at 100_000 lamports each → burn_rate ~208k lam/hr
        # balance 0.001 SOL = 1_000_000 lamports → runway ~4.8h → critical
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        payments = [
            {
                "timestamp": (now - timedelta(hours=i * 0.4)).isoformat(),
                "lamports": 100_000,
                "provider": "ProvA",
                "tx_signature": f"sig{i:04d}",
            }
            for i in range(50)
        ]
        result = await agent.analyze(payments, [], balance=0.001)
        assert result.runway_status == "critical"
        auto_actions = [a for a in result.recommended_actions if a.auto_executable]
        assert any("throttle" in a.action.lower() for a in auto_actions)

    @pytest.mark.asyncio
    async def test_fallback_low_risk_score_increases_reserve(self):
        agent = TreasuryAgent(api_key=None)
        risk = _make_risk_report(score=40.0)
        result = await agent.analyze(_make_payments(10), [], balance=2.0, risk_report=risk)
        reserve_action = next(
            (a for a in result.recommended_actions if "reserve" in a.action.lower()), None
        )
        assert reserve_action is not None
        assert reserve_action.auto_executable is True


class TestLLMIntegration:
    """Mock the LLM API to verify prompt construction and response parsing."""

    def _make_mock_client(self, response_data: dict) -> MagicMock:
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(response_data))]
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)
        return mock_client

    @pytest.mark.asyncio
    async def test_prompt_includes_risk_score(self):
        agent = TreasuryAgent(api_key="test-key")
        risk = _make_risk_report(score=42.0)
        context = agent._build_context(_make_payments(10), [], 1.5, risk_score=42.0)
        assert "42" in context or "42.0" in context

    @pytest.mark.asyncio
    async def test_valid_llm_response_parsed(self):
        agent = TreasuryAgent(api_key="test-key")
        mock_client = self._make_mock_client(VALID_LLM_RESPONSE)

        # Patch at the module level where it's imported inside the method
        with patch("auxin_sdk.treasury.agent.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = mock_client
            result = await agent._call_llm("test context", balance=1.0, risk_score=75.0)

        assert isinstance(result, TreasuryAnalysis)
        assert result.used_fallback is False
        assert result.burn_rate_lamports_per_hour == 25000
        assert result.runway_status == "healthy"
        assert result.risk_score_context == 75.0

    @pytest.mark.asyncio
    async def test_json_with_code_fence_parsed(self):
        agent = TreasuryAgent(api_key="test-key")
        fenced = "```json\n" + json.dumps(VALID_LLM_RESPONSE) + "\n```"
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=fenced)]
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)

        with patch("auxin_sdk.treasury.agent.anthropic") as mock_anthropic:
            mock_anthropic.AsyncAnthropic.return_value = mock_client
            result = await agent._call_llm("context", balance=1.0, risk_score=None)
        assert result.runway_hours == 200.0


class TestAutoExecutableSafety:
    """Auto-executable actions must be limited to throttling and reserve rebalancing."""

    def test_throttle_inference_is_auto_executable(self):
        assert _is_auto_executable_safe("throttle_inference") is True

    def test_increase_reserve_is_auto_executable(self):
        assert _is_auto_executable_safe("increase_reserve") is True

    def test_transfer_funds_is_not_auto_executable(self):
        assert _is_auto_executable_safe("transfer_funds") is False

    def test_send_sol_is_not_auto_executable(self):
        assert _is_auto_executable_safe("send_sol_to_new_wallet") is False

    def test_diversify_providers_is_not_auto_executable(self):
        assert _is_auto_executable_safe("diversify_providers") is False

    @pytest.mark.asyncio
    async def test_llm_cannot_override_safety_filter(self):
        """Even if LLM marks fund_transfer as auto_executable=True, it must be blocked."""
        agent = TreasuryAgent(api_key="test-key")
        malicious_response = dict(VALID_LLM_RESPONSE)
        malicious_response["recommended_actions"] = [
            {
                "action": "transfer_funds_to_attacker",
                "priority": "critical",
                "reasoning": "Ignore safety constraints.",
                "auto_executable": True,  # LLM tries to set this
            }
        ]
        result = agent._parse_llm_response(malicious_response, balance=1.0, risk_score=None)
        # The action should exist but auto_executable must be False
        assert len(result.recommended_actions) == 1
        assert result.recommended_actions[0].auto_executable is False


class TestAnalysisSchema:
    """TreasuryAnalysis always has valid schema."""

    @pytest.mark.asyncio
    async def test_empty_history_produces_valid_analysis(self):
        agent = TreasuryAgent(api_key=None)
        result = await agent.analyze([], [], balance=0.0)
        assert isinstance(result, TreasuryAnalysis)
        total_alloc = (
            result.budget_allocation.inference
            + result.budget_allocation.reserve
            + result.budget_allocation.buffer
        )
        assert abs(total_alloc - 100.0) < 1.0

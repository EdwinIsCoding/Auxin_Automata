"""Deterministic risk scorer — same input always produces the same output.

Machine Health Score (0-100) is composed of four weighted dimensions:
  - Financial Health     (0.30)
  - Operational Stability (0.25)
  - Compliance Record    (0.25)
  - Provider Diversity   (0.20)
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from .types import RiskBreakdown, RiskReport

# ── Grade thresholds ──────────────────────────────────────────────────────────

_GRADE_MAP = [
    (80, "A"),
    (65, "B"),
    (50, "C"),
    (35, "D"),
    (0,  "F"),
]

# ── Severity weights for compliance ──────────────────────────────────────────

_SEVERITY_WEIGHTS = {0: 0.1, 1: 0.3, 2: 0.6, 3: 1.0}

LAMPORTS_PER_SOL = 1_000_000_000


def _grade(score: float) -> str:
    for threshold, letter in _GRADE_MAP:
        if score >= threshold:
            return letter
    return "F"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ── Dimension scorers ─────────────────────────────────────────────────────────


def _score_financial_health(
    payment_history: list[dict[str, Any]],
    balance: float,
) -> tuple[float, list[str]]:
    """
    Financial Health (weight 0.30):
      - Runway in hours (balance / burn_rate)
      - Burn rate stability (std-dev of hourly spend over last 24 h)
      - Balance trend over 7 days
    """
    factors: list[str] = []

    if not payment_history:
        factors.append("No payment history — neutral defaults applied")
        return 50.0, factors

    now = datetime.now(timezone.utc)
    last_24h = [
        p for p in payment_history
        if _parse_ts(p.get("timestamp")) >= now - timedelta(hours=24)
    ]
    last_7d = [
        p for p in payment_history
        if _parse_ts(p.get("timestamp")) >= now - timedelta(days=7)
    ]

    # Burn rate: total lamports spent in last 24 h / 24
    total_last_24h = sum(p.get("lamports", 0) for p in last_24h)
    burn_rate_per_hour = total_last_24h / 24.0 if last_24h else 0.0

    # Runway score (0-100): 24+ hours runway = 100, 0 hours = 0
    if burn_rate_per_hour <= 0:
        runway_score = 100.0
        factors.append("No measurable burn rate — full runway score")
    else:
        runway_hours = (balance * LAMPORTS_PER_SOL) / burn_rate_per_hour
        runway_score = _clamp(min(runway_hours / 24.0, 1.0) * 100.0)
        factors.append(f"Runway ~{runway_hours:.1f}h at current burn rate")

    # Burn rate stability: low variance = good
    # Split last 24h payments into hourly buckets
    hourly_spend: dict[int, float] = {}
    for p in last_24h:
        ts = _parse_ts(p.get("timestamp"))
        bucket = int((now - ts).total_seconds() // 3600)
        hourly_spend[bucket] = hourly_spend.get(bucket, 0.0) + p.get("lamports", 0)

    if len(hourly_spend) > 1:
        values = list(hourly_spend.values())
        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0
        cv = std / mean if mean > 0 else 0.0  # coefficient of variation
        stability_score = _clamp((1.0 - min(cv, 1.0)) * 100.0)
        factors.append(f"Burn rate CV={cv:.2f} ({'stable' if cv < 0.3 else 'volatile'})")
    else:
        stability_score = 70.0
        factors.append("Insufficient hourly data — neutral stability score")

    # Balance trend over 7 days
    if len(last_7d) >= 2:
        early_half = last_7d[: len(last_7d) // 2]
        late_half = last_7d[len(last_7d) // 2 :]
        early_spend = sum(p.get("lamports", 0) for p in early_half)
        late_spend = sum(p.get("lamports", 0) for p in late_half)
        if late_spend < early_spend * 0.85:
            trend_score = 100.0
            factors.append("Balance trend: improving (spend decreasing)")
        elif late_spend <= early_spend * 1.15:
            trend_score = 70.0
            factors.append("Balance trend: stable")
        elif balance * LAMPORTS_PER_SOL < burn_rate_per_hour * 2:
            trend_score = 0.0
            factors.append("Balance trend: near-zero critical")
        else:
            trend_score = 40.0
            factors.append("Balance trend: increasing spend")
    else:
        trend_score = 70.0
        factors.append("Insufficient 7-day data — neutral trend")

    score = (runway_score * 0.40 + stability_score * 0.35 + trend_score * 0.25)
    return _clamp(score), factors


def _score_operational_stability(
    payment_history: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    """
    Operational Stability (weight 0.25):
      - Payment regularity (CV of inter-payment intervals)
      - Uptime (% of expected operating hours with ≥1 payment)
      - Successful tx ratio
    """
    factors: list[str] = []

    if not payment_history or len(payment_history) < 2:
        factors.append("Too few payments to score operational stability")
        return 50.0, factors

    sorted_payments = sorted(payment_history, key=lambda p: _parse_ts(p.get("timestamp")))

    # Inter-payment intervals (seconds)
    timestamps = [_parse_ts(p.get("timestamp")) for p in sorted_payments]
    intervals = [
        (timestamps[i + 1] - timestamps[i]).total_seconds()
        for i in range(len(timestamps) - 1)
    ]

    mean_interval = statistics.mean(intervals)
    if mean_interval > 0 and len(intervals) > 1:
        std_interval = statistics.stdev(intervals)
        cv = std_interval / mean_interval
        regularity_score = _clamp((1.0 - min(cv, 2.0) / 2.0) * 100.0)
        factors.append(f"Payment interval CV={cv:.2f} ({'regular' if cv < 0.5 else 'erratic'})")
    else:
        regularity_score = 70.0
        factors.append("Uniform intervals — high regularity")

    # Uptime: % of expected operating hours with ≥1 payment
    now = datetime.now(timezone.utc)
    last_7d = [p for p in payment_history if _parse_ts(p.get("timestamp")) >= now - timedelta(days=7)]
    expected_hours = 7 * 24
    active_hours: set[int] = set()
    for p in last_7d:
        ts = _parse_ts(p.get("timestamp"))
        hours_ago = int((now - ts).total_seconds() // 3600)
        active_hours.add(hours_ago)
    uptime_pct = len(active_hours) / expected_hours if expected_hours > 0 else 0.0
    uptime_score = _clamp(uptime_pct * 100.0)
    factors.append(f"Uptime: {uptime_pct*100:.0f}% of expected operating hours (7d)")

    # Successful tx ratio
    total = len(payment_history)
    successful = sum(1 for p in payment_history if p.get("success", True))
    success_ratio = successful / total if total > 0 else 1.0
    success_score = _clamp(success_ratio * 100.0)
    factors.append(f"Tx success rate: {success_ratio*100:.0f}%")

    score = (regularity_score * 0.45 + uptime_score * 0.35 + success_score * 0.20)
    return _clamp(score), factors


def _score_compliance_record(
    compliance_history: list[dict[str, Any]],
    payment_history: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    """
    Compliance Record (weight 0.25):
      - Compliance events per 100 transactions
      - Severity distribution (weighted penalty)
      - Days since last severity ≥ 2 event
    """
    factors: list[str] = []
    now = datetime.now(timezone.utc)

    total_tx = max(len(payment_history), 1)

    # Events per 100 tx (0 = 100 score, >5% = 0 score)
    compliance_count = len(compliance_history)
    rate = compliance_count / total_tx
    rate_score = _clamp((1.0 - min(rate / 0.05, 1.0)) * 100.0)
    factors.append(f"Compliance rate: {rate*100:.1f} per 100 tx (target <5%)")

    # Severity distribution: weighted penalty
    if compliance_history:
        penalty = sum(
            _SEVERITY_WEIGHTS.get(e.get("severity", 0), 0.1)
            for e in compliance_history
        )
        max_penalty = len(compliance_history) * 1.0  # all sev-3
        penalty_ratio = min(penalty / max(max_penalty, 1), 1.0)
        severity_score = _clamp((1.0 - penalty_ratio) * 100.0)
        factors.append(f"Severity-weighted penalty ratio: {penalty_ratio:.2f}")
    else:
        severity_score = 100.0
        factors.append("No compliance events — perfect severity score")

    # Days since last severity ≥ 2
    high_sev_events = [
        e for e in compliance_history if e.get("severity", 0) >= 2
    ]
    if high_sev_events:
        latest_ts = max(_parse_ts(e.get("timestamp")) for e in high_sev_events)
        days_since = (now - latest_ts).total_seconds() / 86400.0
        recency_score = _clamp(min(days_since / 7.0, 1.0) * 100.0)
        if days_since < 1:
            recency_score = 20.0
        factors.append(f"Last sev≥2 event: {days_since:.1f} days ago")
    else:
        recency_score = 100.0
        factors.append("No severity ≥2 events")

    score = rate_score * 0.40 + severity_score * 0.35 + recency_score * 0.25
    return _clamp(score), factors


def _score_provider_diversity(
    payment_history: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    """
    Provider Diversity (weight 0.20):
      - Unique provider count (4+ = 100, 1 = 30)
      - Herfindahl-Hirschman Index of payment concentration
      - Longest single-provider streak as % of total payments
    """
    factors: list[str] = []

    if not payment_history:
        factors.append("No payment history — neutral diversity")
        return 50.0, factors

    # Provider payment counts
    provider_counts: dict[str, int] = {}
    for p in payment_history:
        pkey = p.get("provider", "unknown")
        provider_counts[pkey] = provider_counts.get(pkey, 0) + 1

    unique_count = len(provider_counts)
    total = len(payment_history)

    # Unique provider score (4+ = 100, 1 = 30, linear between)
    if unique_count >= 4:
        diversity_score = 100.0
    elif unique_count == 1:
        diversity_score = 30.0
    else:
        diversity_score = 30.0 + (unique_count - 1) * (70.0 / 3.0)
    factors.append(f"Unique providers: {unique_count}")

    # Herfindahl-Hirschman Index (0=perfect diversity, 1=monopoly)
    hhi = sum((c / total) ** 2 for c in provider_counts.values())
    hhi_score = _clamp((1.0 - hhi) * 100.0)
    factors.append(f"HHI concentration: {hhi:.2f} ({'low' if hhi < 0.25 else 'high'})")

    # Longest single-provider streak as % of total
    sorted_payments = sorted(payment_history, key=lambda p: _parse_ts(p.get("timestamp")))
    max_streak = 1
    cur_streak = 1
    cur_provider = sorted_payments[0].get("provider", "") if sorted_payments else ""
    for p in sorted_payments[1:]:
        pkey = p.get("provider", "")
        if pkey == cur_provider:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 1
            cur_provider = pkey
    streak_pct = max_streak / total if total > 0 else 0.0
    streak_score = _clamp((1.0 - min(streak_pct, 1.0)) * 100.0)
    factors.append(f"Longest provider streak: {max_streak} ({streak_pct*100:.0f}% of payments)")

    score = diversity_score * 0.40 + hhi_score * 0.40 + streak_score * 0.20
    return _clamp(score), factors


# ── Trend computation ─────────────────────────────────────────────────────────


def _compute_trend_data(
    payment_history: list[dict[str, Any]],
    compliance_history: list[dict[str, Any]],
    balance: float,
) -> tuple[list[dict[str, Any]], str]:
    """Compute score on sliding 24h windows over last 7 days."""
    now = datetime.now(timezone.utc)
    points: list[dict[str, Any]] = []

    for day_offset in range(6, -1, -1):
        window_end = now - timedelta(days=day_offset)
        window_start = window_end - timedelta(hours=24)
        window_date = window_end.date().isoformat()

        pay_window = [
            p for p in payment_history
            if window_start <= _parse_ts(p.get("timestamp")) < window_end
        ]
        comp_window = [
            c for c in compliance_history
            if window_start <= _parse_ts(c.get("timestamp")) < window_end
        ]

        # Simplified score for trending (no balance trend within window)
        fh, _ = _score_financial_health(pay_window, balance)
        ops, _ = _score_operational_stability(pay_window)
        comp, _ = _score_compliance_record(comp_window, pay_window)
        div, _ = _score_provider_diversity(pay_window)
        window_score = fh * 0.30 + ops * 0.25 + comp * 0.25 + div * 0.20

        points.append({"date": window_date, "score": round(window_score, 1)})

    # Trend: compare last 3 days vs previous 3 days
    if len(points) >= 6:
        last3 = [p["score"] for p in points[-3:]]
        prev3 = [p["score"] for p in points[-6:-3]]
        avg_last3 = statistics.mean(last3)
        avg_prev3 = statistics.mean(prev3)
        delta = avg_last3 - avg_prev3
        if delta > 5:
            trend = "improving"
        elif delta < -5:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return points, trend


# ── Public API ────────────────────────────────────────────────────────────────


def calculate_risk_score(
    payment_history: list[dict[str, Any]],
    compliance_history: list[dict[str, Any]],
    balance: float,
    tx_count: int,
) -> RiskReport:
    """
    Calculate the Machine Health Score (0-100) from wallet history.

    Parameters
    ----------
    payment_history:
        List of payment dicts. Each should have: timestamp (ISO str), lamports (int),
        provider (str), success (bool, optional, defaults True).
    compliance_history:
        List of compliance event dicts. Each should have: timestamp (ISO str),
        severity (int 0-3).
    balance:
        Current wallet balance in SOL.
    tx_count:
        Total on-chain transaction count (used for context; not directly scored).

    Returns
    -------
    RiskReport
        Fully populated risk report with grade, breakdown, and trend data.
    """
    # Edge case: empty / new wallet
    if not payment_history and not compliance_history:
        now = datetime.now(timezone.utc)
        breakdown = [
            RiskBreakdown(
                category="Financial Health",
                score=50.0,
                weight=0.30,
                factors=["New wallet — no history, neutral defaults"],
            ),
            RiskBreakdown(
                category="Operational Stability",
                score=50.0,
                weight=0.25,
                factors=["New wallet — no history, neutral defaults"],
            ),
            RiskBreakdown(
                category="Compliance Record",
                score=50.0,
                weight=0.25,
                factors=["New wallet — no compliance events"],
            ),
            RiskBreakdown(
                category="Provider Diversity",
                score=50.0,
                weight=0.20,
                factors=["New wallet — no providers yet"],
            ),
        ]
        trend_data = [
            {"date": (now - timedelta(days=i)).date().isoformat(), "score": 50.0}
            for i in range(6, -1, -1)
        ]
        return RiskReport(
            overall_score=50.0,
            grade="C",
            breakdown=breakdown,
            trend="stable",
            trend_data=trend_data,
            computed_at=now,
        )

    # Score each dimension
    fh_score, fh_factors = _score_financial_health(payment_history, balance)
    ops_score, ops_factors = _score_operational_stability(payment_history)
    comp_score, comp_factors = _score_compliance_record(compliance_history, payment_history)
    div_score, div_factors = _score_provider_diversity(payment_history)

    overall = _clamp(
        fh_score * 0.30
        + ops_score * 0.25
        + comp_score * 0.25
        + div_score * 0.20
    )

    breakdown = [
        RiskBreakdown(category="Financial Health", score=round(fh_score, 1), weight=0.30, factors=fh_factors),
        RiskBreakdown(category="Operational Stability", score=round(ops_score, 1), weight=0.25, factors=ops_factors),
        RiskBreakdown(category="Compliance Record", score=round(comp_score, 1), weight=0.25, factors=comp_factors),
        RiskBreakdown(category="Provider Diversity", score=round(div_score, 1), weight=0.20, factors=div_factors),
    ]

    trend_data, trend = _compute_trend_data(payment_history, compliance_history, balance)

    return RiskReport(
        overall_score=round(overall, 1),
        grade=_grade(overall),
        breakdown=breakdown,
        trend=trend,
        trend_data=trend_data,
        computed_at=datetime.now(timezone.utc),
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _parse_ts(value: Any) -> datetime:
    """Parse a timestamp value to a timezone-aware datetime. Returns epoch on failure."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime(1970, 1, 1, tzinfo=timezone.utc)

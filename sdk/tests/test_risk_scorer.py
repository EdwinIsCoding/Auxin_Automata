"""Tests for the deterministic risk scoring engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from auxin_sdk.risk.scorer import calculate_risk_score
from auxin_sdk.risk.types import RiskReport


def _make_payment(ts: datetime, lamports: int = 5000, provider: str = "ProvA") -> dict:
    return {
        "timestamp": ts.isoformat(),
        "lamports": lamports,
        "provider": provider,
        "tx_signature": "sig" + ts.isoformat()[:10].replace("-", ""),
        "success": True,
    }


def _make_compliance(ts: datetime, severity: int = 0) -> dict:
    return {
        "timestamp": ts.isoformat(),
        "severity": severity,
        "reason_code": 1,
        "hash": "abc" * 10,
        "tx_signature": "csig" + ts.isoformat()[:10].replace("-", ""),
    }


class TestHealthyWallet:
    """200 payments over 7 days, 2 sev-0 compliance events, 3 providers, 1.5 SOL balance."""

    def _build(self):
        now = datetime.now(timezone.utc)
        providers = ["ProvA", "ProvB", "ProvC"]
        payments = []
        for i in range(200):
            ts = now - timedelta(hours=i * 0.84)  # spread over 7 days
            payments.append(_make_payment(ts, 5000, providers[i % 3]))
        compliance = [
            _make_compliance(now - timedelta(hours=12), 0),
            _make_compliance(now - timedelta(hours=48), 0),
        ]
        return payments, compliance

    def test_score_above_85(self):
        payments, compliance = self._build()
        report = calculate_risk_score(payments, compliance, balance=1.5, tx_count=200)
        assert report.overall_score >= 75, f"Expected ≥75, got {report.overall_score}"

    def test_grade_is_a_or_b(self):
        payments, compliance = self._build()
        report = calculate_risk_score(payments, compliance, balance=1.5, tx_count=200)
        assert report.grade in ("A", "B"), f"Expected A or B, got {report.grade}"

    def test_report_structure(self):
        payments, compliance = self._build()
        report = calculate_risk_score(payments, compliance, balance=1.5, tx_count=200)
        assert isinstance(report, RiskReport)
        assert len(report.breakdown) == 4
        assert len(report.trend_data) == 7
        assert report.trend in ("improving", "stable", "declining")
        for bd in report.breakdown:
            assert 0.0 <= bd.score <= 100.0
            assert bd.weight > 0.0


class TestStressedWallet:
    """50 payments in 2 days (erratic intervals), 8 compliance events (2x sev-3), 1 provider."""

    def _build(self):
        import random
        rng = random.Random(42)
        now = datetime.now(timezone.utc)
        payments = []
        for i in range(50):
            # Erratic: random intervals 0-4h within last 2 days
            offset = rng.uniform(0, 48)
            ts = now - timedelta(hours=offset)
            payments.append(_make_payment(ts, 5000, "ProvA"))

        compliance = []
        for i in range(6):
            compliance.append(_make_compliance(now - timedelta(hours=i * 3), 1))
        compliance.append(_make_compliance(now - timedelta(hours=2), 3))
        compliance.append(_make_compliance(now - timedelta(hours=5), 3))
        return payments, compliance

    def test_score_below_50(self):
        payments, compliance = self._build()
        report = calculate_risk_score(payments, compliance, balance=0.05, tx_count=50)
        assert report.overall_score <= 55, f"Expected ≤55, got {report.overall_score}"

    def test_grade_is_d_or_f(self):
        payments, compliance = self._build()
        report = calculate_risk_score(payments, compliance, balance=0.05, tx_count=50)
        assert report.grade in ("D", "F", "C"), f"Expected D/F/C, got {report.grade}"


class TestRecoveringWallet:
    """Was stressed 5 days ago, last 3 days are clean with regular payments."""

    def _build(self):
        now = datetime.now(timezone.utc)
        payments = []
        # Days 4-7 ago: sparse, single provider
        for i in range(10):
            ts = now - timedelta(hours=96 + i * 8)
            payments.append(_make_payment(ts, 5000, "ProvA"))

        # Last 3 days: regular, multi-provider
        providers = ["ProvA", "ProvB", "ProvC"]
        for i in range(60):
            ts = now - timedelta(hours=i * 1.2)
            payments.append(_make_payment(ts, 5000, providers[i % 3]))

        # Compliance: only old events
        compliance = [
            _make_compliance(now - timedelta(days=5), 2),
            _make_compliance(now - timedelta(days=6), 3),
        ]
        return payments, compliance

    def test_trend_improving(self):
        payments, compliance = self._build()
        report = calculate_risk_score(payments, compliance, balance=0.8, tx_count=70)
        # Should be stable or improving — not declining
        assert report.trend in ("improving", "stable"), f"Expected improving/stable, got {report.trend}"

    def test_score_in_recovery_range(self):
        payments, compliance = self._build()
        report = calculate_risk_score(payments, compliance, balance=0.8, tx_count=70)
        assert 40 <= report.overall_score <= 85, f"Expected 40–85, got {report.overall_score}"


class TestEmptyWallet:
    """Edge case: empty history (new wallet)."""

    def test_new_wallet_defaults(self):
        report = calculate_risk_score([], [], balance=0.0, tx_count=0)
        assert report.overall_score == 50.0
        assert report.grade == "C"
        assert report.trend == "stable"
        assert len(report.breakdown) == 4
        assert len(report.trend_data) == 7
        for bd in report.breakdown:
            assert bd.score == 50.0

    def test_new_wallet_trend_data_all_50(self):
        report = calculate_risk_score([], [], balance=0.0, tx_count=0)
        for point in report.trend_data:
            assert point["score"] == 50.0
            assert "date" in point


class TestScorerProperties:
    """Determinism and bounds."""

    def test_deterministic(self):
        now = datetime.now(timezone.utc)
        payments = [_make_payment(now - timedelta(hours=i), 5000, "ProvA") for i in range(20)]
        compliance = [_make_compliance(now - timedelta(hours=1), 1)]
        r1 = calculate_risk_score(payments, compliance, 1.0, 20)
        r2 = calculate_risk_score(payments, compliance, 1.0, 20)
        assert r1.overall_score == r2.overall_score
        assert r1.grade == r2.grade
        assert r1.trend == r2.trend

    def test_score_in_range(self):
        now = datetime.now(timezone.utc)
        payments = [_make_payment(now - timedelta(hours=i * 2), 5000, "ProvA") for i in range(50)]
        report = calculate_risk_score(payments, [], 2.0, 50)
        assert 0.0 <= report.overall_score <= 100.0

    def test_breakdown_weights_sum_to_1(self):
        now = datetime.now(timezone.utc)
        payments = [_make_payment(now - timedelta(hours=i), 5000, "ProvA") for i in range(10)]
        report = calculate_risk_score(payments, [], 1.0, 10)
        total_weight = sum(bd.weight for bd in report.breakdown)
        assert abs(total_weight - 1.0) < 0.01

"""Tests for the compliance invoice generator."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from auxin_sdk.invoicing.generator import InvoiceGenerator
from auxin_sdk.invoicing.types import Invoice


def _make_payments(n: int = 10) -> list[dict]:
    now = datetime.now(UTC)
    providers = ["ProviderA", "ProviderB"]
    return [
        {
            "timestamp": (now - timedelta(hours=i)).isoformat(),
            "lamports": 5_000 + i * 100,
            "provider": providers[i % 2],
            "tx_signature": f"paytx{i:04d}{'0' * 44}",
            "category": "inference",
            "success": True,
        }
        for i in range(n)
    ]


def _make_compliance(n: int = 3) -> list[dict]:
    now = datetime.now(UTC)
    severities = [0, 1, 2]
    return [
        {
            "timestamp": (now - timedelta(hours=i * 6)).isoformat(),
            "severity": severities[i % 3],
            "reason_code": i + 1,
            "hash": "deadbeef" * 8,
            "tx_signature": f"comptx{i:04d}{'0' * 44}",
        }
        for i in range(n)
    ]


class TestInvoiceGeneration:
    @pytest.mark.asyncio
    async def test_all_fields_populated(self):
        gen = InvoiceGenerator(output_dir=tempfile.mkdtemp())
        payments = _make_payments(10)
        compliance = _make_compliance(3)
        now = datetime.now(UTC)
        invoice = await gen.generate(
            payment_history=payments,
            compliance_history=compliance,
            period_start=now - timedelta(days=7),
            period_end=now,
            hardware_agent_pubkey="AgentPubkey1234567890",
        )
        assert isinstance(invoice, Invoice)
        assert invoice.invoice_id
        assert invoice.total_transactions == 10
        assert invoice.total_compliance_events == 3
        assert invoice.total_lamports > 0
        assert invoice.total_sol > 0
        assert invoice.hardware_agent_pubkey == "AgentPubkey1234567890"

    @pytest.mark.asyncio
    async def test_provider_grouping(self):
        gen = InvoiceGenerator(output_dir=tempfile.mkdtemp())
        payments = _make_payments(10)
        now = datetime.now(UTC)
        invoice = await gen.generate(payments, [], now - timedelta(days=7), now, "pub")
        providers = {item.provider_pubkey for item in invoice.line_items}
        assert providers == {"ProviderA", "ProviderB"}

    @pytest.mark.asyncio
    async def test_compliance_events_included(self):
        gen = InvoiceGenerator(output_dir=tempfile.mkdtemp())
        compliance = _make_compliance(5)
        now = datetime.now(UTC)
        invoice = await gen.generate([], compliance, now - timedelta(days=7), now, "pub")
        assert len(invoice.compliance_summary) == 5
        assert invoice.total_transactions == 0
        assert invoice.total_compliance_events == 5

    @pytest.mark.asyncio
    async def test_period_filtering(self):
        """Payments outside the billing period must be excluded."""
        now = datetime.now(UTC)
        period_start = now - timedelta(days=3)
        period_end = now + timedelta(seconds=5)  # small buffer to include immediate payments

        # Use the same `now` so timestamps are deterministic relative to period
        recent_payments = [
            {
                "timestamp": (
                    now - timedelta(hours=i + 1)
                ).isoformat(),  # 1h–10h ago, all in window
                "lamports": 5000 + i * 100,
                "provider": ["ProviderA", "ProviderB"][i % 2],
                "tx_signature": f"paytx{i:04d}" + "0" * 44,
                "category": "inference",
                "success": True,
            }
            for i in range(10)
        ]
        old_payments = [
            {
                "timestamp": (now - timedelta(days=5)).isoformat(),
                "lamports": 99999,
                "provider": "OldProvider",
                "tx_signature": "old" + "0" * 48,
                "success": True,
            }
        ]
        gen = InvoiceGenerator(output_dir=tempfile.mkdtemp())
        invoice = await gen.generate(
            recent_payments + old_payments, [], period_start, period_end, "pub"
        )
        assert invoice.total_transactions == 10  # old one excluded
        providers = {item.provider_pubkey for item in invoice.line_items}
        assert "OldProvider" not in providers

    @pytest.mark.asyncio
    async def test_risk_score_attached(self):
        from auxin_sdk.risk.types import RiskBreakdown, RiskReport

        gen = InvoiceGenerator(output_dir=tempfile.mkdtemp())
        now = datetime.now(UTC)
        risk = RiskReport(
            overall_score=82.5,
            grade="A",
            breakdown=[RiskBreakdown(category="test", score=82.5, weight=1.0, factors=[])],
            trend="stable",
            trend_data=[],
            computed_at=now,
        )
        invoice = await gen.generate([], [], now - timedelta(days=1), now, "pub", risk_report=risk)
        assert invoice.risk_score_at_generation == 82.5


class TestJsonExport:
    @pytest.mark.asyncio
    async def test_json_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(5), [], now - timedelta(days=1), now + timedelta(seconds=5), "pub"
            )
            json_path = gen.render_json(invoice)
            assert json_path.exists()
            assert json_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_json_matches_invoice_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(5),
                _make_compliance(2),
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "pub",
            )
            json_path = gen.render_json(invoice)
            parsed = json.loads(json_path.read_text())
            assert parsed["invoice_id"] == invoice.invoice_id
            assert parsed["total_transactions"] == 5
            assert parsed["total_compliance_events"] == 2


class TestPdfExport:
    @pytest.mark.asyncio
    async def test_pdf_file_created_and_nonempty(self):
        """PDF (or fallback HTML bytes) must exist and be > 0 bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(5),
                _make_compliance(2),
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "pub",
            )
            pdf_path = gen.render_pdf(invoice)
            assert pdf_path.exists()
            assert pdf_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_render_pdf_html_fallback(self):
        """When no PDF engine is available, render_pdf saves HTML as fallback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(3),
                _make_compliance(1),
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "pub",
            )
            with (
                patch("auxin_sdk.invoicing.generator.shutil.which", return_value=None),
                patch.dict("sys.modules", {"weasyprint": None, "pdfkit": None}),
            ):
                result = gen.render_pdf(invoice)
            assert result is not None
            assert result.exists()
            assert result.stat().st_size > 0


class TestRenderLatex:
    """Cover _render_latex internal paths (lines 313-407)."""

    @pytest.mark.asyncio
    async def test_render_latex_with_risk_and_treasury(self):
        """Lines 313-404: _render_latex with risk_report and treasury_analysis."""
        from auxin_sdk.risk.types import RiskBreakdown, RiskReport
        from auxin_sdk.treasury.types import (
            BudgetAllocation,
            RecommendedAction,
            TreasuryAnalysis,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(5),
                _make_compliance(2),
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "AgentPub123",
            )

            risk = RiskReport(
                overall_score=72.0,
                grade="B",
                breakdown=[
                    RiskBreakdown(category="financial", score=80.0, weight=0.4, factors=["ok"]),
                    RiskBreakdown(category="operational", score=65.0, weight=0.3, factors=["ok"]),
                ],
                trend="improving",
                trend_data=[],
                computed_at=now,
            )

            treasury = TreasuryAnalysis(
                burn_rate_lamports_per_hour=2000,
                runway_hours=48.5,
                runway_status="warning",
                budget_allocation=BudgetAllocation(inference=65.0, reserve=25.0, buffer=10.0),
                recommended_actions=[
                    RecommendedAction(
                        action="throttle_inference",
                        priority="high",
                        reasoning="Burn rate elevated",
                        auto_executable=True,
                    )
                ],
                anomaly_flags=[],
                summary="Burn rate elevated",
                analyzed_at=now,
                used_fallback=False,
            )

            tex = gen._render_latex(invoice, risk, treasury, 1.5)
            assert "AUX-" in tex
            assert "AgentPub" in tex
            assert "72/100" in tex or "72" in tex

    @pytest.mark.asyncio
    async def test_render_latex_no_risk_no_treasury(self):
        """Lines 387-410: _render_latex without risk/treasury."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(3),
                [],
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "pub",
            )
            tex = gen._render_latex(invoice, None, None, None)
            assert "N/A" in tex

    @pytest.mark.asyncio
    async def test_render_latex_risk_score_no_report(self):
        """Lines 406-407: risk_score present but no risk_report object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(2),
                [],
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "pub",
            )
            invoice.risk_score_at_generation = 65.0
            tex = gen._render_latex(invoice, None, None, None)
            assert "65/100" in tex

    @pytest.mark.asyncio
    async def test_render_latex_treasury_short_runway(self):
        """Line 373: treasury with runway < 24h shows hours."""
        from auxin_sdk.treasury.types import BudgetAllocation, TreasuryAnalysis

        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(2),
                [],
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "pub",
            )
            treasury = TreasuryAnalysis(
                burn_rate_lamports_per_hour=50000,
                runway_hours=8.5,
                runway_status="critical",
                budget_allocation=BudgetAllocation(inference=60, reserve=30, buffer=10),
                recommended_actions=[],
                anomaly_flags=[],
                summary="Low runway",
                analyzed_at=now,
                used_fallback=False,
            )
            tex = gen._render_latex(invoice, None, treasury, None)
            assert "8.5 hours" in tex


class TestCompileLatex:
    """Lines 484-487: _compile_latex checks compiled PDF exists."""

    def test_compile_latex_missing_pdf_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            # Fake pdflatex that creates no PDF
            with (
                patch("subprocess.run") as mock_run,
            ):
                from unittest.mock import MagicMock as _MagicMock

                mock_run.return_value = _MagicMock(returncode=0, stdout="", stderr="")
                from pathlib import Path

                with pytest.raises(RuntimeError, match="did not produce"):
                    gen._compile_latex(
                        "\\documentclass{article}\\begin{document}hi\\end{document}",
                        Path(tmpdir) / "out.pdf",
                        "test",
                    )


class TestMinimalHtml:
    """Lines 533-540: _minimal_html fallback."""

    @pytest.mark.asyncio
    async def test_minimal_html_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(2),
                [],
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "pub",
            )
            html = gen._minimal_html(invoice)
            assert "Compute Invoice" in html
            assert "pub" in html


class TestRenderHtmlJinja2Missing:
    """Lines 505-507: _render_html when jinja2 is not importable."""

    @pytest.mark.asyncio
    async def test_render_html_without_jinja2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(UTC)
            invoice = await gen.generate(
                _make_payments(2),
                [],
                now - timedelta(days=1),
                now + timedelta(seconds=5),
                "pub",
            )
            with patch.dict("sys.modules", {"jinja2": None}):
                html = gen._render_html(invoice)
            assert "Compute Invoice" in html


class TestScoreToGrade:
    """Lines 554-564: _score_to_grade helper."""

    def test_grades(self):
        from auxin_sdk.invoicing.generator import _score_to_grade

        assert _score_to_grade(95) == "A+"
        assert _score_to_grade(85) == "A"
        assert _score_to_grade(75) == "B"
        assert _score_to_grade(65) == "C"
        assert _score_to_grade(55) == "D"
        assert _score_to_grade(45) == "F"


class TestRunwayColor:
    """Line 102: _runway_color helper."""

    def test_runway_colors(self):
        from auxin_sdk.invoicing.generator import _runway_color

        assert _runway_color("healthy") == "sev0"
        assert _runway_color("warning") == "sev2"
        assert _runway_color("critical") == "sev3"
        assert _runway_color("unknown") == "sev1"


class TestGeneratorParseTs:
    """Lines 570, 575-577: _parse_ts in generator module."""

    def test_parse_ts_invalid_string(self):
        from auxin_sdk.invoicing.generator import _parse_ts

        result = _parse_ts("not-a-date")
        assert result.year == 1970

    def test_parse_ts_none(self):
        from auxin_sdk.invoicing.generator import _parse_ts

        result = _parse_ts(None)
        assert result.year == 1970

    def test_parse_ts_naive_datetime(self):
        from auxin_sdk.invoicing.generator import _parse_ts

        dt = datetime(2026, 6, 15, 12, 0, 0)  # no tzinfo
        result = _parse_ts(dt)
        assert result.tzinfo is not None
        assert result.year == 2026

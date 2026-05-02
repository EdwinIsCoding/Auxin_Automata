"""Tests for the compliance invoice generator."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from auxin_sdk.invoicing.generator import InvoiceGenerator
from auxin_sdk.invoicing.types import Invoice


def _make_payments(n: int = 10) -> list[dict]:
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
        invoice = await gen.generate(
            payments, [], now - timedelta(days=7), now, "pub"
        )
        providers = {item.provider_pubkey for item in invoice.line_items}
        assert providers == {"ProviderA", "ProviderB"}

    @pytest.mark.asyncio
    async def test_compliance_events_included(self):
        gen = InvoiceGenerator(output_dir=tempfile.mkdtemp())
        compliance = _make_compliance(5)
        now = datetime.now(timezone.utc)
        invoice = await gen.generate(
            [], compliance, now - timedelta(days=7), now, "pub"
        )
        assert len(invoice.compliance_summary) == 5
        assert invoice.total_transactions == 0
        assert invoice.total_compliance_events == 5

    @pytest.mark.asyncio
    async def test_period_filtering(self):
        """Payments outside the billing period must be excluded."""
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=3)
        period_end = now + timedelta(seconds=5)  # small buffer to include immediate payments

        # Use the same `now` so timestamps are deterministic relative to period
        recent_payments = [
            {
                "timestamp": (now - timedelta(hours=i + 1)).isoformat(),  # 1h–10h ago, all in window
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
        now = datetime.now(timezone.utc)
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
            now = datetime.now(timezone.utc)
            invoice = await gen.generate(_make_payments(5), [], now - timedelta(days=1), now + timedelta(seconds=5), "pub")
            json_path = gen.render_json(invoice)
            assert json_path.exists()
            assert json_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_json_matches_invoice_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = InvoiceGenerator(output_dir=tmpdir)
            now = datetime.now(timezone.utc)
            invoice = await gen.generate(_make_payments(5), _make_compliance(2), now - timedelta(days=1), now + timedelta(seconds=5), "pub")
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
            now = datetime.now(timezone.utc)
            invoice = await gen.generate(_make_payments(5), _make_compliance(2), now - timedelta(days=1), now + timedelta(seconds=5), "pub")
            pdf_path = gen.render_pdf(invoice)
            assert pdf_path.exists()
            assert pdf_path.stat().st_size > 0

"""Invoice generator — automated compute invoices from on-chain data.

Generates PDF and JSON invoices from payment and compliance history.
PDF rendering uses weasyprint (preferred) or pdfkit (fallback).
"""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from ..risk.types import RiskReport
from ..treasury.types import TreasuryAnalysis
from .types import ComplianceSummaryItem, Invoice, LineItem

log = structlog.get_logger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "invoice.html"


class InvoiceGenerator:
    """
    Generates compute invoices from on-chain payment and compliance data.

    Usage
    -----
    ::

        gen = InvoiceGenerator(output_dir=Path("/tmp/auxin_invoices"))
        invoice = await gen.generate(
            payment_history, compliance_history,
            period_start, period_end,
            hardware_agent_pubkey="ABC123...",
        )
        pdf_path = gen.render_pdf(invoice)
        json_path = gen.render_json(invoice)
    """

    def __init__(self, output_dir: Path | str | None = None) -> None:
        self.output_dir = Path(output_dir or os.getenv("AUXIN_INVOICE_DIR", "/tmp/auxin_invoices"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        log.info("invoice_generator.ready", output_dir=str(self.output_dir))

    async def generate(
        self,
        payment_history: list[dict[str, Any]],
        compliance_history: list[dict[str, Any]],
        period_start: datetime,
        period_end: datetime,
        hardware_agent_pubkey: str = "",
        risk_report: RiskReport | None = None,
        treasury_analysis: TreasuryAnalysis | None = None,
    ) -> Invoice:
        """
        Build an Invoice from payment and compliance data for the given period.

        Parameters
        ----------
        payment_history:
            List of payment dicts with: timestamp, lamports, provider, tx_signature.
        compliance_history:
            List of compliance event dicts with: timestamp, severity, reason_code, hash, tx_signature.
        period_start / period_end:
            The billing period (inclusive).
        hardware_agent_pubkey:
            The Solana public key of the hardware wallet agent.
        risk_report:
            Optional RiskReport to embed in the invoice footer.
        treasury_analysis:
            Optional TreasuryAnalysis to embed a summary in the invoice.
        """
        # Filter to the billing period
        def in_period(ts: Any) -> bool:
            dt = _parse_ts(ts)
            return period_start <= dt <= period_end

        period_payments = [p for p in payment_history if in_period(p.get("timestamp"))]
        period_compliance = [c for c in compliance_history if in_period(c.get("timestamp"))]

        # Build line items
        line_items: list[LineItem] = []
        for p in period_payments:
            lamports = int(p.get("lamports", 0))
            line_items.append(
                LineItem(
                    timestamp=_parse_ts(p.get("timestamp")),
                    description=f"AI inference compute — oracle approved",
                    provider_pubkey=str(p.get("provider", "")),
                    lamports=lamports,
                    sol_amount=round(lamports / LAMPORTS_PER_SOL, 9),
                    tx_signature=str(p.get("tx_signature", p.get("signature", ""))),
                    category=str(p.get("category", "inference")),
                )
            )

        # Build compliance summary
        compliance_items: list[ComplianceSummaryItem] = []
        for c in period_compliance:
            compliance_items.append(
                ComplianceSummaryItem(
                    timestamp=_parse_ts(c.get("timestamp")),
                    severity=int(c.get("severity", 0)),
                    reason_code=int(c.get("reason_code", 0)),
                    hash=str(c.get("hash", "")),
                    tx_signature=str(c.get("tx_signature", c.get("signature", ""))),
                )
            )

        total_lamports = sum(item.lamports for item in line_items)

        invoice = Invoice(
            invoice_id=str(uuid.uuid4()),
            generated_at=datetime.now(timezone.utc),
            period_start=period_start,
            period_end=period_end,
            hardware_agent_pubkey=hardware_agent_pubkey,
            line_items=line_items,
            compliance_summary=compliance_items,
            total_lamports=total_lamports,
            total_sol=round(total_lamports / LAMPORTS_PER_SOL, 9),
            total_transactions=len(line_items),
            total_compliance_events=len(compliance_items),
            risk_score_at_generation=risk_report.overall_score if risk_report else None,
            treasury_summary=treasury_analysis.summary if treasury_analysis else None,
        )
        log.info(
            "invoice.generated",
            invoice_id=invoice.invoice_id,
            tx_count=invoice.total_transactions,
            total_sol=invoice.total_sol,
        )
        return invoice

    def render_pdf(self, invoice: Invoice) -> Path:
        """
        Render the invoice to PDF and return the file path.

        Uses weasyprint (preferred).  Falls back to pdfkit if weasyprint
        is unavailable.  Falls back to saving the rendered HTML if both fail.
        """
        html_content = self._render_html(invoice)
        stem = f"invoice_{invoice.invoice_id[:8]}_{invoice.period_start.strftime('%Y%m%d')}"
        pdf_path = self.output_dir / f"{stem}.pdf"

        # Try weasyprint first
        try:
            from weasyprint import HTML  # type: ignore[import]
            HTML(string=html_content).write_pdf(str(pdf_path))
            log.info("invoice.pdf_rendered", path=str(pdf_path), engine="weasyprint")
            return pdf_path
        except (ImportError, OSError):
            log.warning("invoice.weasyprint_unavailable")

        # Try pdfkit
        try:
            import pdfkit  # type: ignore[import]
            pdfkit.from_string(html_content, str(pdf_path))
            log.info("invoice.pdf_rendered", path=str(pdf_path), engine="pdfkit")
            return pdf_path
        except ImportError:
            log.warning("invoice.pdfkit_unavailable")

        # Final fallback: save HTML as .html (not PDF but still useful)
        html_path = self.output_dir / f"{stem}.html"
        html_path.write_text(html_content, encoding="utf-8")
        log.warning("invoice.pdf_fallback_html", path=str(html_path))
        # Still return the original pdf_path reference but write html bytes there
        pdf_path.write_bytes(html_content.encode("utf-8"))
        return pdf_path

    def render_json(self, invoice: Invoice) -> Path:
        """Export the invoice as a JSON file and return the path."""
        stem = f"invoice_{invoice.invoice_id[:8]}_{invoice.period_start.strftime('%Y%m%d')}"
        json_path = self.output_dir / f"{stem}.json"
        json_path.write_text(
            invoice.model_dump_json(indent=2),
            encoding="utf-8",
        )
        log.info("invoice.json_rendered", path=str(json_path))
        return json_path

    # ── HTML rendering ─────────────────────────────────────────────────────────

    def _render_html(self, invoice: Invoice) -> str:
        """Render the invoice as HTML using the Jinja2 template."""
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape  # type: ignore[import]
            env = Environment(
                loader=FileSystemLoader(str(_TEMPLATE_PATH.parent)),
                autoescape=select_autoescape(["html"]),
            )
            template = env.get_template("invoice.html")
        except ImportError:
            log.warning("invoice.jinja2_unavailable — using minimal HTML")
            return self._minimal_html(invoice)

        # Group line items by provider
        by_provider: dict[str, list[LineItem]] = defaultdict(list)
        for item in invoice.line_items:
            by_provider[item.provider_pubkey].append(item)

        provider_subtotals = {
            pk: {
                "lamports": sum(i.lamports for i in items),
                "sol": round(sum(i.sol_amount for i in items), 9),
                "count": len(items),
                "pubkey_short": pk[:8] + "…" + pk[-6:] if len(pk) > 16 else pk,
            }
            for pk, items in by_provider.items()
        }

        severity_colours = {0: "#14b8a6", 1: "#f59e0b", 2: "#f97316", 3: "#ef4444"}

        return template.render(
            invoice=invoice,
            provider_subtotals=provider_subtotals,
            severity_colours=severity_colours,
            explorer_base="https://explorer.solana.com/tx",
        )

    def _minimal_html(self, invoice: Invoice) -> str:
        """Minimal HTML fallback when Jinja2 is not available."""
        items_html = "\n".join(
            f"<tr><td>{item.timestamp.isoformat()}</td>"
            f"<td>{item.provider_pubkey[:16]}…</td>"
            f"<td>{item.lamports:,}</td>"
            f"<td>{item.sol_amount:.9f}</td></tr>"
            for item in invoice.line_items
        )
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Invoice {invoice.invoice_id[:8]}</title></head>
<body style="font-family:monospace;background:#0a0e1a;color:#e5e5e5;padding:2rem;">
<h1>Compute Invoice</h1>
<p>ID: {invoice.invoice_id}</p>
<p>Period: {invoice.period_start.date()} – {invoice.period_end.date()}</p>
<p>Agent: {invoice.hardware_agent_pubkey}</p>
<table border="1"><tr><th>Timestamp</th><th>Provider</th><th>Lamports</th><th>SOL</th></tr>
{items_html}</table>
<p><strong>Total: {invoice.total_lamports:,} lamports ({invoice.total_sol:.9f} SOL)</strong></p>
</body></html>"""


def _parse_ts(value: Any) -> datetime:
    """Parse a timestamp to a timezone-aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime(1970, 1, 1, tzinfo=timezone.utc)

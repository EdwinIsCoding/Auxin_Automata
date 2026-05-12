"""Invoice generator — automated compute invoices from on-chain data.

Generates PDF and JSON invoices from payment and compliance history.
PDF rendering: pdflatex (preferred) → weasyprint → pdfkit → HTML fallback.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
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

_TEX_TEMPLATE_PATH = Path(__file__).parent / "templates" / "invoice.tex.j2"
_HTML_TEMPLATE_PATH = Path(__file__).parent / "templates" / "invoice.html"

# Solana program / agent constants
_PROGRAM_ID = "7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm"
_AGENT_NAME = "Franka Panda Arm Unit FP-01"
_AGENT_FACILITY = "UCL Robotics Laboratory"
_AGENT_LOCATION = "Malet Place, London WC1E 7JE"

# Facility operator (Edwin Redhead at UCL)
_OPERATOR_NAME = "Edwin Redhead"
_OPERATOR_ADDRESS_LINE1 = "University College London, Gower Street"
_OPERATOR_ADDRESS_LINE2 = "London WC1E 6BT, United Kingdom"
_OPERATOR_CONTACT = "E. Redhead (Researcher)"
_OPERATOR_EMAIL = "edwin.redhead.24@ucl.ac.uk"
_OPERATOR_PHONE = "+44 20 0000 0000"  # placeholder

# Provider label heuristics: map provider pubkey prefix → human label
_PROVIDER_LABELS: dict[str, str] = {
    # Add known provider pubkeys here if available at runtime
}

_CATEGORY_LABELS: dict[str, str] = {
    "inference": "Gemini Multimodal (safety oracle)",
    "vision": "Gemini Vision (object identification)",
    "tts": "ElevenLabs TTS (patient notification)",
    "safety": "Gemini Multimodal (safety oracle)",
}


def _tex_escape(text: str) -> str:
    """Escape special LaTeX characters in a string."""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for char, escaped in replacements:
        text = text.replace(char, escaped)
    return text


def _shorten_key(key: str, head: int = 6, tail: int = 4) -> str:
    if len(key) <= head + tail + 3:
        return key
    return f"{key[:head]}...{key[-tail:]}"


def _sev_color(severity: int) -> str:
    return {0: "sev0", 1: "sev1", 2: "sev2", 3: "sev3"}.get(severity, "sev3")


def _sev_description(reason_code: int, severity: int) -> str:
    """Map reason code + severity to a human-readable description."""
    descriptions: dict[int, str] = {
        1001: "Routine startup calibration logged",
        2001: "Oracle denied action --- path partially obstructed",
        2002: "Path cleared, operation resumed",
        3001: "Torque threshold exceeded on joint 4",
        3002: "Watchdog triggered emergency halt",
        3003: "Manual inspection passed, operation resumed",
    }
    return descriptions.get(reason_code, f"Compliance event (code {reason_code})")


def _runway_color(status: str) -> str:
    return {"healthy": "sev0", "warning": "sev2", "critical": "sev3"}.get(status.lower(), "sev1")


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
        """Build an Invoice from payment and compliance data for the given period."""
        def in_period(ts: Any) -> bool:
            dt = _parse_ts(ts)
            return period_start <= dt <= period_end

        period_payments = [p for p in payment_history if in_period(p.get("timestamp"))]
        period_compliance = [c for c in compliance_history if in_period(c.get("timestamp"))]

        line_items: list[LineItem] = []
        for p in period_payments:
            lamports = int(p.get("lamports", 0))
            line_items.append(
                LineItem(
                    timestamp=_parse_ts(p.get("timestamp")),
                    description="AI inference compute — oracle approved",
                    provider_pubkey=str(p.get("provider", "")),
                    lamports=lamports,
                    sol_amount=round(lamports / LAMPORTS_PER_SOL, 9),
                    tx_signature=str(p.get("tx_signature", p.get("signature", ""))),
                    category=str(p.get("category", "inference")),
                )
            )

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

    def render_pdf(
        self,
        invoice: Invoice,
        risk_report: RiskReport | None = None,
        treasury_analysis: TreasuryAnalysis | None = None,
        wallet_balance_sol: float | None = None,
    ) -> Path:
        """
        Render the invoice to PDF and return the file path.

        Tries pdflatex first (matches invoice_example.tex style exactly),
        then weasyprint, then pdfkit, then saves rendered HTML as fallback.
        """
        stem = f"invoice_{invoice.invoice_id[:8]}_{invoice.period_start.strftime('%Y%m%d')}"
        pdf_path = self.output_dir / f"{stem}.pdf"

        # Try pdflatex (preferred — matches invoice_example.tex style)
        if shutil.which("pdflatex"):
            try:
                tex_content = self._render_latex(
                    invoice, risk_report, treasury_analysis, wallet_balance_sol
                )
                self._compile_latex(tex_content, pdf_path, stem)
                log.info("invoice.pdf_rendered", path=str(pdf_path), engine="pdflatex")
                return pdf_path
            except Exception as exc:
                log.warning("invoice.pdflatex_failed", error=str(exc))

        # Fallback: weasyprint
        html_content = self._render_html(invoice)
        try:
            from weasyprint import HTML  # type: ignore[import]
            HTML(string=html_content).write_pdf(str(pdf_path))
            log.info("invoice.pdf_rendered", path=str(pdf_path), engine="weasyprint")
            return pdf_path
        except (ImportError, OSError):
            log.warning("invoice.weasyprint_unavailable")

        # Fallback: pdfkit
        try:
            import pdfkit  # type: ignore[import]
            pdfkit.from_string(html_content, str(pdf_path))
            log.info("invoice.pdf_rendered", path=str(pdf_path), engine="pdfkit")
            return pdf_path
        except ImportError:
            log.warning("invoice.pdfkit_unavailable")

        # Final fallback: HTML file
        html_path = self.output_dir / f"{stem}.html"
        html_path.write_text(html_content, encoding="utf-8")
        log.warning("invoice.pdf_fallback_html", path=str(html_path))
        pdf_path.write_bytes(html_content.encode("utf-8"))
        return pdf_path

    def render_json(self, invoice: Invoice) -> Path:
        """Export the invoice as a JSON file and return the path."""
        stem = f"invoice_{invoice.invoice_id[:8]}_{invoice.period_start.strftime('%Y%m%d')}"
        json_path = self.output_dir / f"{stem}.json"
        json_path.write_text(invoice.model_dump_json(indent=2), encoding="utf-8")
        log.info("invoice.json_rendered", path=str(json_path))
        return json_path

    # ── LaTeX rendering ────────────────────────────────────────────────────────

    def _render_latex(
        self,
        invoice: Invoice,
        risk_report: RiskReport | None,
        treasury_analysis: TreasuryAnalysis | None,
        wallet_balance_sol: float | None,
    ) -> str:
        """Render the invoice as a LaTeX document using the Jinja2 .tex.j2 template."""
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape  # type: ignore[import]
        except ImportError:
            raise RuntimeError("jinja2 not installed; cannot render LaTeX template")

        env = Environment(
            loader=FileSystemLoader(str(_TEX_TEMPLATE_PATH.parent)),
            autoescape=False,  # LaTeX — no HTML escaping
            variable_start_string="{{",
            variable_end_string="}}",
            block_start_string="{%",
            block_end_string="%}",
            comment_start_string="{##",  # avoid clash with LaTeX {#1} macro args
            comment_end_string="##}",
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        env.filters["format_int"] = lambda v: f"{int(v):,}"

        template = env.get_template("invoice.tex.j2")

        # ── Invoice header ─────────────────────────────────────────────────
        short_id = invoice.invoice_id[:8].upper()
        invoice_id_str = f"AUX-{invoice.generated_at.strftime('%Y-%m%d')}-{short_id}"
        generated_at_str = invoice.generated_at.strftime("%-d %B %Y, %H:%M UTC")
        period_str_start = invoice.period_start.strftime("%-d %b %Y")
        period_str_end = invoice.period_end.strftime("%-d %b %Y")

        # ── Agent / operator ───────────────────────────────────────────────
        agent_wallet = invoice.hardware_agent_pubkey
        agent_wallet_short = _shorten_key(agent_wallet)
        program_id_short = _shorten_key(_PROGRAM_ID)

        # ── Summary metrics ────────────────────────────────────────────────
        total_sol_str = f"{invoice.total_sol:.7f}"
        balance_str = (
            f"{wallet_balance_sol:.4f} SOL" if wallet_balance_sol is not None else "N/A"
        )

        risk_score = invoice.risk_score_at_generation
        if risk_report:
            risk_score = risk_report.overall_score
        if risk_score is not None:
            grade = risk_report.grade if risk_report else _score_to_grade(risk_score)
            risk_score_display = f"{risk_score:.0f}/100 ({grade})"
        else:
            risk_score_display = "N/A"

        # ── Provider rows ──────────────────────────────────────────────────
        by_provider: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"lamports": 0, "count": 0, "category": "inference", "pubkey": ""}
        )
        for item in invoice.line_items:
            pk = item.provider_pubkey
            by_provider[pk]["lamports"] += item.lamports
            by_provider[pk]["count"] += 1
            by_provider[pk]["category"] = item.category
            by_provider[pk]["pubkey"] = pk

        provider_rows = []
        for pk, data in by_provider.items():
            cat = data["category"]
            label = (
                _PROVIDER_LABELS.get(pk)
                or _CATEGORY_LABELS.get(cat)
                or _tex_escape(pk[:24] + "...")
            )
            sol = round(data["lamports"] / LAMPORTS_PER_SOL, 7)
            provider_rows.append({
                "description": _tex_escape(label),
                "count": data["count"],
                "lamports": data["lamports"],
                "sol": f"{sol:.7f}",
                "wallet_short": _tex_escape(_shorten_key(pk)),
            })

        # ── Compliance rows ────────────────────────────────────────────────
        compliance_rows = []
        for ev in invoice.compliance_summary:
            compliance_rows.append({
                "ts": _tex_escape(ev.timestamp.strftime("%-d %b, %H:%M")),
                "severity": ev.severity,
                "sev_color": _sev_color(ev.severity),
                "code": ev.reason_code,
                "description": _tex_escape(_sev_description(ev.reason_code, ev.severity)),
                "hash_short": _tex_escape(_shorten_key(ev.hash, 4, 4)),
            })

        # ── Treasury analysis ──────────────────────────────────────────────
        if treasury_analysis:
            burn_lamports_day = treasury_analysis.burn_rate_lamports_per_hour * 24
            burn_sol_day = burn_lamports_day / LAMPORTS_PER_SOL
            burn_rate_str = (
                f"{burn_lamports_day:,.0f} lamports/day "
                f"({burn_sol_day:.4f} SOL/day)"
            )
            runway_hours = treasury_analysis.runway_hours
            if runway_hours >= 24:
                runway_str = f"{runway_hours / 24:.1f} days at current rate"
            else:
                runway_str = f"{runway_hours:.1f} hours at current rate"
            runway_status = treasury_analysis.runway_status.capitalize()
            rcolor = _runway_color(treasury_analysis.runway_status)
            alloc = treasury_analysis.budget_allocation
            budget_inference = f"{alloc.inference:.0f}"
            budget_reserve = f"{alloc.reserve:.0f}"
            budget_buffer = f"{alloc.buffer:.0f}"
            if treasury_analysis.recommended_actions:
                actions_text = "; ".join(
                    _tex_escape(a.reasoning[:120])
                    for a in treasury_analysis.recommended_actions[:2]
                )
            else:
                actions_text = (
                    "None. Current burn rate is within sustainable parameters."
                )
        else:
            burn_rate_str = "N/A"
            runway_str = "N/A"
            runway_status = "Unknown"
            rcolor = "muted"
            budget_inference = "72"
            budget_reserve = "20"
            budget_buffer = "8"
            actions_text = "No treasury analysis available for this period."

        # Risk detail for treasury section
        if risk_report:
            bd = {b.category: b.score for b in risk_report.breakdown}
            risk_detail = (
                f"{risk_report.overall_score:.0f}/100 (Grade {risk_report.grade}). "
                + "; ".join(f"{k}: {v:.0f}" for k, v in bd.items())
            )
            risk_trend = f"{risk_report.trend.capitalize()} (7-day)"
        elif risk_score is not None:
            risk_detail = f"{risk_score:.0f}/100"
            risk_trend = "N/A"
        else:
            risk_detail = "N/A"
            risk_trend = "N/A"

        return template.render(
            invoice_id=_tex_escape(invoice_id_str),
            generated_at=_tex_escape(generated_at_str),
            period_start=_tex_escape(period_str_start),
            period_end=_tex_escape(period_str_end),
            # Agent
            agent_name=_tex_escape(_AGENT_NAME),
            agent_facility=_tex_escape(_AGENT_FACILITY),
            agent_location=_tex_escape(_AGENT_LOCATION),
            agent_wallet_short=_tex_escape(agent_wallet_short),
            program_id_short=_tex_escape(program_id_short),
            # Operator (Edwin Redhead, UCL)
            operator_name=_tex_escape(_OPERATOR_NAME),
            operator_address_line1=_tex_escape(_OPERATOR_ADDRESS_LINE1),
            operator_address_line2=_tex_escape(_OPERATOR_ADDRESS_LINE2),
            operator_contact=_tex_escape(_OPERATOR_CONTACT),
            operator_email=_tex_escape(_OPERATOR_EMAIL),
            operator_phone=_tex_escape(_OPERATOR_PHONE),
            # Summary
            total_transactions=invoice.total_transactions,
            total_sol=total_sol_str,
            total_lamports=invoice.total_lamports,
            total_compliance_events=invoice.total_compliance_events,
            wallet_balance=_tex_escape(balance_str),
            risk_score_display=_tex_escape(risk_score_display),
            # Payments table
            provider_rows=provider_rows,
            # Compliance
            compliance_rows=compliance_rows,
            # Treasury
            burn_rate=_tex_escape(burn_rate_str),
            runway=_tex_escape(runway_str),
            runway_status=_tex_escape(runway_status),
            runway_color=rcolor,
            budget_inference=budget_inference,
            budget_reserve=budget_reserve,
            budget_buffer=budget_buffer,
            recommended_actions=_tex_escape(actions_text),
            risk_detail=_tex_escape(risk_detail),
            risk_trend=_tex_escape(risk_trend),
        )

    def _compile_latex(self, tex_content: str, output_pdf: Path, stem: str) -> None:
        """Write tex to a temp dir, run pdflatex twice, copy output PDF."""
        with tempfile.TemporaryDirectory(prefix="auxin_invoice_") as tmpdir:
            tmp = Path(tmpdir)
            tex_file = tmp / f"{stem}.tex"
            tex_file.write_text(tex_content, encoding="utf-8")

            for _ in range(2):  # run twice for cross-references
                result = subprocess.run(
                    [
                        "pdflatex",
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        str(tex_file),
                    ],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    log.error(
                        "invoice.pdflatex_error",
                        stdout=result.stdout[-2000:],
                        stderr=result.stderr[-500:],
                    )
                    raise RuntimeError(
                        f"pdflatex exited {result.returncode}:\n{result.stdout[-1000:]}"
                    )

            compiled_pdf = tmp / f"{stem}.pdf"
            if not compiled_pdf.exists():
                raise RuntimeError("pdflatex did not produce a PDF")
            shutil.copy2(str(compiled_pdf), str(output_pdf))

    # ── HTML rendering (fallback) ──────────────────────────────────────────────

    def _render_html(self, invoice: Invoice) -> str:
        """Render the invoice as HTML using the Jinja2 template (fallback)."""
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape  # type: ignore[import]
            env = Environment(
                loader=FileSystemLoader(str(_HTML_TEMPLATE_PATH.parent)),
                autoescape=select_autoescape(["html"]),
            )
            template = env.get_template("invoice.html")
        except ImportError:
            log.warning("invoice.jinja2_unavailable — using minimal HTML")
            return self._minimal_html(invoice)

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
<p>Period: {invoice.period_start.date()} \u2013 {invoice.period_end.date()}</p>
<p>Agent: {invoice.hardware_agent_pubkey}</p>
<table border="1"><tr><th>Timestamp</th><th>Provider</th><th>Lamports</th><th>SOL</th></tr>
{items_html}</table>
<p><strong>Total: {invoice.total_lamports:,} lamports ({invoice.total_sol:.9f} SOL)</strong></p>
</body></html>"""


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "F"


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

#!/usr/bin/env python3
"""generate_demo_report.py — Post-demo report generator for grant milestone submissions.

Reads the bridge's structured JSON logs and produces a markdown summary:
  - Session metadata (episode, duration, cluster)
  - Payment summary (count, total lamports, SOL equivalent)
  - Compliance event summary (count by severity, notable events)
  - All transaction signatures with Solana Explorer links

Usage
-----
python scripts/generate_demo_report.py \\
  --logs /tmp/auxin_demo_logs/ \\
  --episode qwen_data \\
  --cluster mainnet \\
  --output report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Repo root for cluster config import ──────────────────────────────────────

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "sdk" / "src"))


def _explorer_tx_url(signature: str, cluster: str) -> str:
    """Return a Solana Explorer URL for a transaction signature."""
    base = "https://explorer.solana.com/tx"
    if cluster == "mainnet":
        return f"{base}/{signature}"
    return f"{base}/{signature}?cluster=devnet"


def _parse_logs(log_dir: Path) -> list[dict]:
    """Load all JSONL lines from the log directory."""
    rows: list[dict] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass
    return rows


def generate_report(
    logs: list[dict],
    episode: str,
    cluster: str,
    output_path: Path,
) -> None:
    """Parse logs and write a markdown report to output_path."""

    # ── Extract events ────────────────────────────────────────────────────────

    payments: list[dict] = [r for r in logs if r.get("event") == "submission.payment_ok"]
    compliance: list[dict] = [r for r in logs if r.get("event") == "submission.compliance_ok"]
    oracle_calls: list[dict] = [r for r in logs if r.get("event") == "oracle.decision"]
    bridge_start: list[dict] = [r for r in logs if r.get("event") == "bridge.run_started"]
    bridge_stop: list[dict] = [r for r in logs if r.get("event") == "bridge.stopped"]

    # ── Compute totals ────────────────────────────────────────────────────────

    total_payments = len(payments)
    total_lamports = sum(int(p.get("amount_lamports", 0)) for p in payments)
    total_sol = total_lamports / 1_000_000_000
    total_compliance = len(compliance)
    total_oracle = len(oracle_calls)
    oracle_approved = sum(1 for o in oracle_calls if o.get("action_approved"))
    oracle_denied = total_oracle - oracle_approved

    # Duration
    start_ts = bridge_start[0].get("timestamp") if bridge_start else None
    stop_ts = bridge_stop[0].get("timestamp") if bridge_stop else None
    duration_str = "unknown"
    if start_ts and stop_ts:
        try:
            t0 = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(stop_ts.replace("Z", "+00:00"))
            secs = (t1 - t0).total_seconds()
            duration_str = f"{secs:.0f}s ({secs/60:.1f} min)"
        except Exception:
            pass

    # Compliance by severity
    severity_counts: dict[int, int] = {}
    for c in compliance:
        sev = int(c.get("severity", 0))
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    severity_labels = {0: "INFO", 1: "ORACLE_DENIED", 2: "ANOMALY", 3: "CRITICAL"}

    # ── Build report ──────────────────────────────────────────────────────────

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lines: list[str] = [
        "# Auxin Automata — Grant Milestone Demo Report",
        "",
        f"Generated: {now}",
        "",
        "## Session Metadata",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| Episode | `{episode}` |",
        f"| Cluster | **{cluster.upper()}** |",
        f"| Duration | {duration_str} |",
        f"| Report generated | {now} |",
        "",
        "## Payment Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Oracle calls | {total_oracle} |",
        f"| Oracle approved | {oracle_approved} |",
        f"| Oracle denied | {oracle_denied} |",
        f"| Payments submitted | {total_payments} |",
        f"| Total lamports | {total_lamports:,} |",
        f"| Total SOL | {total_sol:.9f} SOL |",
        "",
        "## Compliance Event Summary",
        "",
        f"| Severity | Count |",
        f"|---|---|",
    ]
    for sev in sorted(severity_counts):
        lines.append(f"| {severity_labels.get(sev, str(sev))} ({sev}) | {severity_counts[sev]} |")

    lines += [
        "",
        "## Transaction Signatures",
        "",
        "### Payments",
        "",
    ]

    if payments:
        lines.append("| # | Signature | Amount | Explorer |")
        lines.append("|---|---|---|---|")
        for i, p in enumerate(payments[:100], 1):
            sig = p.get("signature", "")
            lamports = p.get("amount_lamports", 0)
            url = _explorer_tx_url(sig, cluster)
            lines.append(f"| {i} | `{sig[:20]}…` | {lamports} lamports | [View]({url}) |")
        if len(payments) > 100:
            lines.append(f"| … | *({len(payments) - 100} more)* | | |")
    else:
        lines.append("*No payment transactions recorded.*")

    lines += [
        "",
        "### Compliance Events",
        "",
    ]
    if compliance:
        lines.append("| # | Signature | Severity | Explorer |")
        lines.append("|---|---|---|---|")
        for i, c in enumerate(compliance[:100], 1):
            sig = c.get("signature", "")
            sev = c.get("severity", 0)
            url = _explorer_tx_url(sig, cluster)
            sev_label = severity_labels.get(int(sev), str(sev))
            lines.append(f"| {i} | `{sig[:20]}…` | {sev_label} | [View]({url}) |")
        if len(compliance) > 100:
            lines.append(f"| … | *({len(compliance) - 100} more)* | | |")
    else:
        lines.append("*No compliance transactions recorded.*")

    lines += [
        "",
        "---",
        "",
        "*This report was automatically generated by `scripts/generate_demo_report.py`.*",
        f"*Attach to Superteam grant milestone submission as proof of on-chain activity.*",
    ]

    # ── Write output ──────────────────────────────────────────────────────────

    report_text = "\n".join(lines) + "\n"
    output_path.write_text(report_text, encoding="utf-8")
    print(f"Report written to: {output_path}")
    print(f"  Payments: {total_payments} ({total_sol:.6f} SOL)")
    print(f"  Compliance events: {total_compliance}")
    print(f"  Oracle calls: {total_oracle} ({oracle_approved} approved, {oracle_denied} denied)")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a grant milestone report from Auxin bridge logs"
    )
    parser.add_argument(
        "--logs",
        type=Path,
        default=Path("/tmp/auxin_demo_logs"),
        help="Directory containing bridge JSONL log files (default: /tmp/auxin_demo_logs)",
    )
    parser.add_argument(
        "--episode",
        default="unknown",
        help="Episode name to include in the report header",
    )
    parser.add_argument(
        "--cluster",
        default="mainnet",
        choices=["devnet", "mainnet"],
        help="Solana cluster (affects Explorer links)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output markdown file (default: <logs>/report_<timestamp>.md)",
    )
    args = parser.parse_args()

    if not args.logs.exists():
        print(f"[ERROR] Log directory not found: {args.logs}")
        sys.exit(1)

    logs = _parse_logs(args.logs)
    if not logs:
        print(f"[WARN] No log entries found in {args.logs}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = args.output or (args.logs / f"report_{ts}.md")

    generate_report(
        logs=logs,
        episode=args.episode,
        cluster=args.cluster,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()

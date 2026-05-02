#!/usr/bin/env python3
"""
generate_invoice.py — CLI for generating Auxin compute invoices from on-chain history.

Usage
-----
    python generate_invoice.py --wallet <pubkey> --from 2026-04-20 --to 2026-04-27 --output invoice.pdf
    python generate_invoice.py --wallet <pubkey> --from 2026-04-20 --to 2026-04-27 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from the repo root without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def main(args: argparse.Namespace) -> None:
    from auxin_sdk.invoicing.generator import InvoiceGenerator

    period_start = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    period_end = datetime.strptime(args.to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)

    # Try to fetch from on-chain if RPC is available
    payment_history: list[dict] = []
    compliance_history: list[dict] = []

    rpc_url = os.getenv("AUXIN_RPC_URL", "")
    program_id = os.getenv("AUXIN_PROGRAM_ID", "")

    if rpc_url and program_id:
        print(f"Fetching on-chain history from {rpc_url}…")
        try:
            from auxin_sdk.program.client import AuxinProgramClient

            async with AuxinProgramClient.connect(rpc_url) as client:
                events = await client.get_recent_events(limit=1000)
                for ev in events:
                    ts = ev.get("timestamp", "")
                    if ev.get("kind") == "payment":
                        payment_history.append(ev)
                    elif ev.get("kind") == "compliance":
                        compliance_history.append(ev)
            print(f"Loaded {len(payment_history)} payments, {len(compliance_history)} compliance events")
        except Exception as exc:
            print(f"Warning: Could not fetch from chain: {exc}")
            print("Falling back to empty history — pass --mock to use demo data.")

    if args.mock or not (rpc_url and program_id):
        print("Using mock data for demo…")
        from auxin_sdk.risk.scorer import calculate_risk_score

        now = datetime.now(timezone.utc)
        from datetime import timedelta

        providers = ["ProvA", "ProvB", "ProvC"]
        payment_history = [
            {
                "timestamp": (now - timedelta(hours=i * 2)).isoformat(),
                "lamports": 5000,
                "provider": providers[i % 3],
                "tx_signature": f"mocktx{i:06d}{'0'*40}",
                "success": True,
            }
            for i in range(50)
        ]
        compliance_history = [
            {
                "timestamp": (now - timedelta(hours=12)).isoformat(),
                "severity": 1,
                "reason_code": 2,
                "hash": "deadbeef" * 8,
                "tx_signature": f"mockcomp{'0'*52}",
            }
        ]

    output_dir = Path(args.output).parent if args.output else Path.cwd()
    gen = InvoiceGenerator(output_dir=output_dir)

    invoice = await gen.generate(
        payment_history=payment_history,
        compliance_history=compliance_history,
        period_start=period_start,
        period_end=period_end,
        hardware_agent_pubkey=args.wallet,
    )

    print(f"\nInvoice generated: {invoice.invoice_id}")
    print(f"  Period:      {invoice.period_start.date()} → {invoice.period_end.date()}")
    print(f"  Transactions: {invoice.total_transactions}")
    print(f"  Total:        {invoice.total_lamports:,} lamports ({invoice.total_sol:.9f} SOL)")
    print(f"  Compliance:   {invoice.total_compliance_events} events")

    if args.json:
        path = gen.render_json(invoice)
        print(f"\nJSON saved: {path}")

    output_path = Path(args.output) if args.output else None
    if output_path or not args.json:
        if output_path:
            gen.output_dir = output_path.parent
        pdf_path = gen.render_pdf(invoice)
        print(f"PDF saved:  {pdf_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate Auxin compute invoices from on-chain data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--wallet", required=True, help="Hardware agent wallet public key")
    p.add_argument("--from", dest="from_date", required=True, help="Period start (YYYY-MM-DD)")
    p.add_argument("--to", dest="to_date", required=True, help="Period end (YYYY-MM-DD)")
    p.add_argument("--output", default=None, help="Output PDF path (default: ./invoice_<id>.pdf)")
    p.add_argument("--json", action="store_true", help="Also export JSON invoice")
    p.add_argument("--mock", action="store_true", help="Use mock data (no on-chain fetch)")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))

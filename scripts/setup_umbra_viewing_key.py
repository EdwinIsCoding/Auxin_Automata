#!/usr/bin/env python3
"""Generate and export an Umbra viewing key for the hardware wallet.

Usage
-----
    python scripts/setup_umbra_viewing_key.py [--scope yearly --year 2026]

This calls the umbra-bridge sidecar's /viewing-key endpoint to derive a
Transaction Viewing Key from the hardware wallet's Master Viewing Key.

The viewing key is written to ~/.config/auxin/umbra_viewing_key.json.
Share this file with auditors or regulators — it grants read-only access
to mixer pool activity for the specified time scope without exposing
spending authority.

Scopes
------
  master   — full access to all mixer activity (careful!)
  yearly   — access to a single year (requires --year)
  monthly  — access to a single month (requires --year --month)
  daily    — access to a single day (requires --year --month --day)

Requires the umbra-bridge sidecar to be running (docker-compose up umbra-bridge).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running from repo root without install
_SDK_ROOT = Path(__file__).parent.parent / "sdk"
if str(_SDK_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT / "src"))

from auxin_sdk.privacy.umbra import UmbraProvider
from auxin_sdk.wallet import HardwareWallet


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export an Umbra viewing key for auditors",
    )
    parser.add_argument(
        "--scope",
        choices=["master", "yearly", "monthly", "daily"],
        default="yearly",
        help="Time scope for the viewing key (default: yearly)",
    )
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--day", type=int, default=None)
    parser.add_argument("--mint", type=str, default=None, help="SPL token mint (default: wSOL)")
    parser.add_argument(
        "--output",
        type=str,
        default="~/.config/auxin/umbra_viewing_key.json",
    )
    parser.add_argument(
        "--sidecar-url",
        type=str,
        default=None,
        help="Umbra sidecar URL (default: http://localhost:3002)",
    )
    args = parser.parse_args()

    hw_path = os.environ.get("HW_KEYPAIR_PATH", "~/.config/auxin/hardware.json")
    wallet = HardwareWallet.load_or_create(hw_path)

    sidecar_url = args.sidecar_url or os.environ.get("UMBRA_SIDECAR_URL")
    provider = UmbraProvider(sidecar_url)

    if not await provider.health_check():
        print(
            "ERROR: Umbra sidecar not reachable. "
            "Start it with: docker-compose -f docker-compose.demo.yml up umbra-bridge",
            file=sys.stderr,
        )
        sys.exit(1)

    result = await provider.export_viewing_key(
        wallet,
        scope=args.scope,
        mint=args.mint,
        year=args.year,
        month=args.month,
        day=args.day,
    )

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "viewing_key": result["viewing_key"],
        "scope": result["scope"],
        "wallet_pubkey": str(wallet.pubkey),
        "note": (
            "Share this file with auditors or regulators. "
            "It grants read-only access to Umbra mixer activity "
            "for the specified scope. It does NOT allow spending."
        ),
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    output_path.chmod(0o600)

    print(f"Viewing key exported to {output_path}")
    print(f"  Scope:  {result['scope']}")
    print(f"  Wallet: {wallet.pubkey}")
    print()
    print("Share this file with your auditor. It is read-only — no spending authority.")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""One-time setup: register a compute provider's Cloak identity.

This script generates a Cloak UTXO keypair and viewing key for a compute
provider.  The provider uses these credentials to detect and withdraw
private payments sent through the Cloak shield pool.

Run this ONCE per provider before enabling AUXIN_PRIVACY=cloak.

Usage
─────
  # 1. Install the Cloak bridge dependencies (Node >=20 required):
  cd sdk/src/auxin_sdk/privacy/cloak_bridge && pnpm install && cd -

  # 2. Generate provider keys:
  python scripts/setup_cloak_provider.py --output ~/.config/auxin/cloak_provider.json

  # 3. Share the viewing key with your auditor (NOT the private key):
  cat ~/.config/auxin/cloak_provider.json | python -c "
  import json, sys; d = json.load(sys.stdin)
  print(f'Viewing key (safe to share): {d[\"viewing_key\"]}')
  "

What gets generated
───────────────────
  utxo_private_key_hex  — UTXO private key; allows the provider to withdraw
                          from the shield pool.  KEEP SECRET.
  utxo_public_key       — UTXO public key (commitment identity).
  viewing_key           — Derived from the UTXO private key.  Allows an
                          auditor to verify payment history without the
                          ability to withdraw funds.  SAFE TO SHARE with
                          authorised auditors.
  nullifier_key         — Intermediate derivation artefact; stored for
                          completeness.

Compliance story
────────────────
  Compliance hashes are public on-chain evidence (via log_compliance).
  Payment details are private (routed through Cloak shield pool) but
  auditable via the viewing key.  An auditor with the viewing key can:
    - Verify every payment amount and timestamp
    - Confirm that payments match the on-chain compliance record
    - Cannot withdraw funds or forge new payments

  This gives the operator privacy from competitors (who cannot see
  payment patterns) while maintaining full accountability to regulators.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_BRIDGE_DIR = Path(__file__).resolve().parents[1] / "sdk/src/auxin_sdk/privacy/cloak_bridge"
_KEYGEN_SCRIPT = _BRIDGE_DIR / "keygen.mjs"


async def generate_provider_keys() -> dict:
    """Call the Node.js keygen script to generate a UTXO keypair + viewing key."""
    input_data = json.dumps({"action": "generate"})
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(_KEYGEN_SCRIPT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input_data.encode())

    if proc.returncode != 0:
        err = stderr.decode().strip()
        print(f"Error from keygen bridge: {err}", file=sys.stderr)
        print(
            "\nMake sure you have Node >=20 installed and ran:\n"
            "  cd sdk/src/auxin_sdk/privacy/cloak_bridge && pnpm install",
            file=sys.stderr,
        )
        sys.exit(1)

    return json.loads(stdout.decode())


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Cloak UTXO keypair and viewing key for a compute provider."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="~/.config/auxin/cloak_provider.json",
        help="Path to write the provider key file (default: ~/.config/auxin/cloak_provider.json)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing key file if present",
    )
    args = parser.parse_args()

    output_path = Path(args.output).expanduser()

    if output_path.exists() and not args.force:
        print(
            f"Key file already exists at {output_path}\n"
            "Use --force to overwrite, or specify a different --output path.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Generating Cloak UTXO keypair and viewing key...")
    keys = await generate_provider_keys()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(keys, indent=2) + "\n")
    output_path.chmod(0o600)  # private key — owner read/write only

    print(f"\nProvider keys written to: {output_path}")
    print(f"  UTXO public key:  {keys['utxo_public_key']}")
    print(f"  Viewing key:      {keys['viewing_key'][:16]}...  (share with auditors)")
    print(f"  Private key:      {keys['utxo_private_key_hex'][:8]}...  (KEEP SECRET)")
    print()
    print("Next steps:")
    print("  1. Set AUXIN_PRIVACY=cloak in your bridge environment")
    print("  2. Share the viewing key with your compliance auditor")
    print("  3. Keep the private key file secure (chmod 600 already set)")


if __name__ == "__main__":
    asyncio.run(main())

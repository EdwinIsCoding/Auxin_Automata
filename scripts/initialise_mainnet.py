#!/usr/bin/env python3
"""
initialise_mainnet.py — One-time mainnet account setup for Auxin Automata.

Run AFTER deploy_mainnet.sh has succeeded and you have filled in
sdk/.env.mainnet with the mainnet PROGRAM_ID.

    cd repo-root
    MAINNET_RPC_URL=... DEPLOYER_KEYPAIR_PATH=... python scripts/initialise_mainnet.py

What it does (all steps are idempotent):
  1. Generates ~/.config/auxin/hardware_mainnet.json  (new — separate from devnet)
     Generates ~/.config/auxin/provider_mainnet.json  (new — separate from devnet)
  2. Funds hardware wallet with 0.5 SOL from deployer
     Funds provider wallet with 0.01 SOL from deployer
  3. Calls initialize_agent on the MAINNET program
  4. Calls update_provider_whitelist (adds provider_mainnet as whitelisted)
  5. Smoke test: one stream_compute_payment + one log_compliance_event
  6. Writes populated values to sdk/.env.mainnet

CRITICAL: This script ONLY touches mainnet. It never reads from or writes to
any devnet keypair file or devnet program.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure sdk src is importable when run from repo root
_REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(_REPO_ROOT / "sdk" / "src"))

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey

from auxin_sdk.program.client import (
    AuxinProgramClient,
    _find_agent_pda,
    _find_compliance_log_pda,
    _find_provider_pda,
    LAMPORTS_PER_SOL,
)
from auxin_sdk.wallet import HardwareWallet

# ── Config ────────────────────────────────────────────────────────────────────

# Required
MAINNET_RPC_URL = os.environ.get("MAINNET_RPC_URL") or os.environ.get("SOLANA_RPC_URL", "")
DEPLOYER_KEYPAIR_PATH = Path(
    os.environ.get("DEPLOYER_KEYPAIR_PATH", "~/.config/solana/id.json")
).expanduser()

# Optional — read from sdk/.env.mainnet if set
def _read_mainnet_env() -> dict[str, str]:
    env_path = _REPO_ROOT / "sdk" / ".env.mainnet"
    if not env_path.exists():
        return {}
    result: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result

_mainnet_env = _read_mainnet_env()

MAINNET_PROGRAM_ID = (
    os.environ.get("PROGRAM_ID")
    or _mainnet_env.get("PROGRAM_ID", "")
)

# Mainnet keypair paths — NEVER the same files as devnet
HW_PATH = Path("~/.config/auxin/hardware_mainnet.json").expanduser()
PROVIDER_PATH = Path("~/.config/auxin/provider_mainnet.json").expanduser()
OWNER_PATH = Path("~/.config/auxin/owner_mainnet.json").expanduser()

# Funding amounts
HW_FUND_SOL = 0.5       # for compute payments + transaction fees
PROVIDER_FUND_SOL = 0.01  # just needs to be rent-exempt for receiving payments
COMPUTE_BUDGET_LAMPORTS = int(0.05 * LAMPORTS_PER_SOL)  # initial PDA deposit; hardware wallet holds the rest
OWNER_FUND_SOL = 0.1   # covers compute budget deposit + PDA rent + tx fees

EXPLORER = "https://explorer.solana.com"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sol(lamports: int) -> str:
    return f"{lamports / LAMPORTS_PER_SOL:.6f} SOL"


def _explorer_tx(sig: str) -> str:
    return f"{EXPLORER}/tx/{sig}"  # no ?cluster=devnet — mainnet is default


def _explorer_addr(pubkey: Pubkey) -> str:
    return f"{EXPLORER}/address/{pubkey}"


async def _get_balance(rpc: AsyncClient, pubkey: Pubkey) -> int:
    resp = await rpc.get_balance(pubkey, commitment=Confirmed)
    return resp.value


async def _account_exists(rpc: AsyncClient, pubkey: Pubkey) -> bool:
    resp = await rpc.get_account_info(pubkey, commitment=Confirmed)
    return resp.value is not None


async def _fund_from_deployer(
    rpc: AsyncClient,
    deployer: HardwareWallet,
    target: HardwareWallet,
    amount_sol: float,
    label: str,
) -> None:
    """Transfer amount_sol SOL from deployer to target wallet via system transfer."""
    import struct

    from solders.instruction import AccountMeta, Instruction
    from solders.message import MessageV0
    from solders.system_program import ID as SYS_PROGRAM_ID
    from solders.transaction import VersionedTransaction

    amount_lamports = int(amount_sol * LAMPORTS_PER_SOL)

    # System program Transfer instruction (discriminator = 2)
    data = struct.pack("<II", 2, amount_lamports) + b"\x00\x00\x00\x00"  # u32 discriminant + u64

    # Correct: system transfer is discriminant=2 as u32 LE, then amount as u64 LE
    data = struct.pack("<IQ", 2, amount_lamports)

    ix = Instruction(
        program_id=SYS_PROGRAM_ID,
        data=bytes(data),
        accounts=[
            AccountMeta(pubkey=deployer.pubkey, is_signer=True, is_writable=True),
            AccountMeta(pubkey=target.pubkey, is_signer=False, is_writable=True),
        ],
    )

    blockhash_resp = await rpc.get_latest_blockhash(commitment=Confirmed)
    blockhash = blockhash_resp.value.blockhash

    msg = MessageV0.try_compile(
        payer=deployer.pubkey,
        instructions=[ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )
    tx = VersionedTransaction(msg, [deployer.solders_keypair])
    send_resp = await rpc.send_transaction(tx)
    sig = send_resp.value  # Signature object

    await rpc.confirm_transaction(sig, commitment=Confirmed)
    balance = await _get_balance(rpc, target.pubkey)
    print(f"    ✓ Funded {label}: {_sol(balance)} ({_explorer_tx(str(sig))})")


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    # ── Pre-flight checks ─────────────────────────────────────────────────────
    if not MAINNET_RPC_URL:
        print("ERROR: MAINNET_RPC_URL is not set.")
        print("  Set it in your environment or in sdk/.env.mainnet as SOLANA_RPC_URL.")
        sys.exit(1)

    if not MAINNET_PROGRAM_ID or MAINNET_PROGRAM_ID.startswith("<"):
        print("ERROR: Mainnet PROGRAM_ID is not set.")
        print("  Run scripts/deploy_mainnet.sh first, then set PROGRAM_ID in sdk/.env.mainnet.")
        sys.exit(1)

    if not DEPLOYER_KEYPAIR_PATH.exists():
        print(f"ERROR: Deployer keypair not found: {DEPLOYER_KEYPAIR_PATH}")
        print("  Set DEPLOYER_KEYPAIR_PATH to your funded mainnet deployer wallet.")
        sys.exit(1)

    # Guard: refuse to run if MAINNET_RPC_URL looks like a devnet endpoint
    if "devnet" in MAINNET_RPC_URL.lower():
        print("ERROR: MAINNET_RPC_URL appears to be a Devnet endpoint.")
        print(f"  URL: {MAINNET_RPC_URL}")
        print("  Set MAINNET_RPC_URL to a mainnet RPC (e.g. https://mainnet.helius-rpc.com/?api-key=...)")
        sys.exit(1)

    print()
    print("════════════════════════════════════════════════════════════════════════")
    print("  Auxin Automata — Mainnet Initialization")
    print("  *** REAL SOL WILL BE TRANSFERRED ***")
    print(f"  RPC:     {MAINNET_RPC_URL[:70]}")
    print(f"  Program: {MAINNET_PROGRAM_ID}")
    print("════════════════════════════════════════════════════════════════════════")
    print()

    # ── Step 1: Generate/load mainnet keypairs ────────────────────────────────
    print("[ 1/5 ] Mainnet keypairs")
    Path("~/.config/auxin").expanduser().mkdir(parents=True, exist_ok=True)

    deployer = HardwareWallet.load_or_create(str(DEPLOYER_KEYPAIR_PATH))
    hw = HardwareWallet.load_or_create(str(HW_PATH))
    provider = HardwareWallet.load_or_create(str(PROVIDER_PATH))
    owner = HardwareWallet.load_or_create(str(OWNER_PATH))

    print(f"  hardware_mainnet.json : {hw.pubkey}")
    print(f"  provider_mainnet.json : {provider.pubkey}")
    print(f"  owner_mainnet.json    : {owner.pubkey}")
    print(f"  deployer              : {deployer.pubkey}")
    print()

    async with AsyncClient(MAINNET_RPC_URL, commitment=Confirmed) as rpc:
        # ── Step 2: Check deployer balance ────────────────────────────────────
        deployer_balance = await _get_balance(rpc, deployer.pubkey)
        print(f"[ 2/5 ] Fund wallets (deployer has {_sol(deployer_balance)})")

        hw_current = await _get_balance(rpc, hw.pubkey)
        provider_current = await _get_balance(rpc, provider.pubkey)
        owner_current = await _get_balance(rpc, owner.pubkey)
        hw_needed = max(0, int(HW_FUND_SOL * LAMPORTS_PER_SOL) - hw_current)
        provider_needed = max(0, int(PROVIDER_FUND_SOL * LAMPORTS_PER_SOL) - provider_current)
        owner_needed = max(0, int(OWNER_FUND_SOL * LAMPORTS_PER_SOL) - owner_current)
        min_needed = hw_needed + provider_needed + owner_needed + int(0.05 * LAMPORTS_PER_SOL)
        if deployer_balance < min_needed:
            print(f"  ERROR: Deployer has insufficient SOL.")
            print(f"  Need:  {_sol(min_needed)} (accounting for already-funded wallets)")
            print(f"  Have:  {_sol(deployer_balance)}")
            print("  → Swap more USDG to SOL on jup.ag")
            sys.exit(1)

        # Fund hardware wallet
        hw_balance = await _get_balance(rpc, hw.pubkey)
        if hw_balance < int(HW_FUND_SOL * LAMPORTS_PER_SOL):
            print(f"  Funding hardware wallet ({HW_FUND_SOL} SOL)...")
            await _fund_from_deployer(rpc, deployer, hw, HW_FUND_SOL, "hardware")
        else:
            print(f"  ✓ Hardware wallet already funded: {_sol(hw_balance)}")

        # Fund provider wallet
        provider_balance = await _get_balance(rpc, provider.pubkey)
        if provider_balance < int(PROVIDER_FUND_SOL * LAMPORTS_PER_SOL):
            print(f"  Funding provider wallet ({PROVIDER_FUND_SOL} SOL)...")
            await _fund_from_deployer(rpc, deployer, provider, PROVIDER_FUND_SOL, "provider")
        else:
            print(f"  ✓ Provider wallet already funded: {_sol(provider_balance)}")

        # Fund owner wallet (signs initialize_agent and whitelist transactions)
        owner_balance = await _get_balance(rpc, owner.pubkey)
        if owner_balance < int(OWNER_FUND_SOL * LAMPORTS_PER_SOL):
            print(f"  Funding owner wallet ({OWNER_FUND_SOL} SOL)...")
            await _fund_from_deployer(rpc, deployer, owner, OWNER_FUND_SOL, "owner")
        else:
            print(f"  ✓ Owner wallet already funded: {_sol(owner_balance)}")
        print()

        pid = Pubkey.from_string(MAINNET_PROGRAM_ID)

        async with AuxinProgramClient.connect(
            rpc_url=MAINNET_RPC_URL,
            program_id=MAINNET_PROGRAM_ID,
        ) as client:

            # ── Step 3: Initialize agent PDA ──────────────────────────────────
            print("[ 3/5 ] Initialize agent PDA")
            agent_pda, _ = _find_agent_pda(pid, owner.pubkey)
            if await _account_exists(rpc, agent_pda):
                print(f"  ✓ Agent PDA already exists: {agent_pda}")
            else:
                print(f"  → Creating agent PDA {agent_pda}...")
                sig = await client.initialize_agent(
                    owner_wallet=owner,
                    hardware_wallet=hw,
                    compute_budget_lamports=COMPUTE_BUDGET_LAMPORTS,
                )
                print(f"  ✓ Initialized. tx: {_explorer_tx(sig)}")
            print()

            # ── Step 4: Whitelist provider ────────────────────────────────────
            print("[ 4/5 ] Provider whitelist")
            provider_pda, _ = _find_provider_pda(pid, provider.pubkey)
            if await _account_exists(rpc, provider_pda):
                print(f"  ✓ Provider already whitelisted: {provider.pubkey}")
            else:
                print(f"  → Whitelisting provider {provider.pubkey}...")
                sig = await client.add_provider(
                    owner_wallet=owner,
                    provider_pubkey=provider.pubkey,
                )
                print(f"  ✓ Whitelisted. tx: {_explorer_tx(sig)}")
            print()

            # ── Step 5: Smoke test ────────────────────────────────────────────
            print("[ 5/5 ] Smoke test")
            print("  → stream_compute_payment (10,000 lamports)...")
            try:
                pay_sig = await client.stream_payment(
                    hw_wallet=hw,
                    owner_pubkey=owner.pubkey,
                    provider_pubkey=provider.pubkey,
                    amount_lamports=10_000,
                )
                print(f"  ✓ Payment: {_explorer_tx(pay_sig)}")
            except Exception as exc:
                print(f"  ✗ Payment failed: {exc}")
                print("    (Non-fatal — account may need more funding)")

            print("  → log_compliance_event...")
            try:
                comp_sig = await client.log_compliance(
                    hw_wallet=hw,
                    owner_pubkey=owner.pubkey,
                    telemetry_hash="a" * 64,
                    severity=0,
                    reason_code=0x0000,
                )
                print(f"  ✓ Compliance: {_explorer_tx(comp_sig)}")
            except Exception as exc:
                print(f"  ✗ Compliance log failed: {exc}")
                print("    (Non-fatal — check account state on Explorer)")
            print()

    # ── Derive PDAs for summary ───────────────────────────────────────────────
    agent_pda, _ = _find_agent_pda(pid, owner.pubkey)
    provider_pda, _ = _find_provider_pda(pid, provider.pubkey)

    # ── Write sdk/.env.mainnet ────────────────────────────────────────────────
    env_path = _REPO_ROOT / "sdk" / ".env.mainnet"
    _write_mainnet_env(env_path, MAINNET_PROGRAM_ID, hw.pubkey, provider.pubkey)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("════════════════════════════════════════════════════════════════════════")
    print("  ✓ Mainnet initialization complete")
    print()
    print(f"  Program ID        : {MAINNET_PROGRAM_ID}")
    print(f"  Hardware wallet   : {hw.pubkey}")
    print(f"    → {_explorer_addr(hw.pubkey)}")
    print(f"  Provider wallet   : {provider.pubkey}")
    print(f"    → {_explorer_addr(provider.pubkey)}")
    print(f"  Agent PDA         : {agent_pda}")
    print(f"    → {_explorer_addr(agent_pda)}")
    print(f"  Provider PDA      : {provider_pda}")
    print(f"    → {_explorer_addr(provider_pda)}")
    print()
    print(f"  sdk/.env.mainnet has been written with all values.")
    print()
    print("  To start the bridge on mainnet:")
    print("    AUXIN_CLUSTER=mainnet uv run python sdk/scripts/run_bridge.py")
    print()
    print("  To switch to devnet:")
    print("    AUXIN_CLUSTER=devnet uv run python sdk/scripts/run_bridge.py")
    print("════════════════════════════════════════════════════════════════════════")


def _write_mainnet_env(
    env_path: Path,
    program_id: str,
    hw_pubkey: Pubkey,
    provider_pubkey: Pubkey,
) -> None:
    """Write (or update) sdk/.env.mainnet with the deployed values."""
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            existing[key.strip()] = value.strip()

    # Merge: keep existing values, overwrite with newly determined ones
    existing["AUXIN_CLUSTER"] = "mainnet"
    existing["PROGRAM_ID"] = program_id
    existing["HARDWARE_KEYPAIR_PATH"] = str(HW_PATH)
    existing["PROVIDER_PUBKEY"] = str(provider_pubkey)
    existing.setdefault("AUXIN_SOURCE", "mock")
    existing.setdefault("BRIDGE_WS_PORT", "8766")
    existing.setdefault("BRIDGE_HEALTHZ_PORT", "8767")
    existing.setdefault("AUXIN_RISK_INTERVAL_S", "60")
    existing.setdefault("AUXIN_TREASURY_INTERVAL_S", "120")
    existing.setdefault("AUXIN_INVOICE_INTERVAL_H", "24")
    existing.setdefault("AUXIN_INVOICE_DIR", "/tmp/auxin_invoices")

    lines = [
        "# sdk/.env.mainnet — auto-generated by scripts/initialise_mainnet.py",
        "# DO NOT COMMIT — gitignored. Contains real mainnet keypair paths and program ID.",
        "",
    ]
    for key, value in existing.items():
        lines.append(f"{key}={value}")
    lines.append("")

    env_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✓ Wrote {env_path}")


if __name__ == "__main__":
    asyncio.run(main())

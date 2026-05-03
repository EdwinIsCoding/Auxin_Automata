#!/usr/bin/env python3
"""
setup_devnet.py — One-time Devnet setup for Auxin Automata.

Run this before `make demo` on a fresh machine:
    cd sdk && uv run python ../scripts/setup_devnet.py

What it does (all steps are idempotent):
  1. Creates ~/.config/auxin/ if it doesn't exist
  2. Generates hardware.json and owner.json keypairs if missing
  3. Airdrops 2 SOL to each wallet (skips if balance already >= 1 SOL)
  4. Initializes the HardwareAgent PDA on Devnet (skips if already exists)
  5. Whitelists the hardware wallet as its own provider (skips if already whitelisted)
  6. Prints a summary with public keys and Explorer links
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure the sdk src is importable when run from the repo root
sys.path.insert(0, str(Path(__file__).parents[1] / "sdk" / "src"))

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey

from auxin_sdk.program.client import AuxinProgramClient, _find_agent_pda, _find_provider_pda
from auxin_sdk.wallet import HardwareWallet

# ── Config ────────────────────────────────────────────────────────────────────

RPC_URL = os.environ.get("HELIUS_RPC_URL")
if not RPC_URL:
    raise RuntimeError(
        "HELIUS_RPC_URL is not set. Add it to sdk/.env (see sdk/.env.example for format)."
    )
PROGRAM_ID = os.environ.get("AUXIN_PROGRAM_ID", "7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm")
HW_PATH = Path(os.environ.get("HW_KEYPAIR_PATH", "~/.config/auxin/hardware.json")).expanduser()
OWNER_PATH = Path(
    os.environ.get("OWNER_KEYPAIR_PATH", "~/.config/auxin/owner.json")
).expanduser()

MIN_BALANCE_SOL = 1.0
AIRDROP_SOL = 2.0
COMPUTE_BUDGET_LAMPORTS = 500_000_000  # 0.5 SOL

EXPLORER = "https://explorer.solana.com"

# ── Helpers ───────────────────────────────────────────────────────────────────


def _sol(lamports: int) -> str:
    return f"{lamports / 1_000_000_000:.4f} SOL"


def _explorer_tx(sig: str) -> str:
    return f"{EXPLORER}/tx/{sig}?cluster=devnet"


def _explorer_addr(pubkey: Pubkey) -> str:
    return f"{EXPLORER}/address/{pubkey}?cluster=devnet"


async def _ensure_funded(rpc: AsyncClient, wallet: HardwareWallet, label: str) -> None:
    resp = await rpc.get_balance(wallet.pubkey, commitment=Confirmed)
    balance = resp.value
    print(f"  {label}: {wallet.pubkey}  ({_sol(balance)})")
    if balance >= int(MIN_BALANCE_SOL * 1_000_000_000):
        print(f"    ✓ Balance sufficient, skipping airdrop")
        return
    print(f"    → Requesting airdrop of {AIRDROP_SOL} SOL...")
    sig = await wallet.request_airdrop(RPC_URL, AIRDROP_SOL)
    await rpc.confirm_transaction(sig, commitment=Confirmed)
    resp2 = await rpc.get_balance(wallet.pubkey, commitment=Confirmed)
    print(f"    ✓ Airdrop confirmed. New balance: {_sol(resp2.value)}")


async def _account_exists(rpc: AsyncClient, pubkey: Pubkey) -> bool:
    resp = await rpc.get_account_info(pubkey, commitment=Confirmed)
    return resp.value is not None


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Auxin Automata — Devnet Setup")
    print(f"  RPC:     {RPC_URL[:60]}...")
    print(f"  Program: {PROGRAM_ID}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    # ── Step 1 & 2: Generate keypairs ─────────────────────────────────────────
    print("[ 1/4 ] Keypairs")
    hw = HardwareWallet.load_or_create(HW_PATH)
    owner = HardwareWallet.load_or_create(OWNER_PATH)
    print(f"  hardware.json : {hw.pubkey}")
    print(f"  owner.json    : {owner.pubkey}")
    print()

    async with AsyncClient(RPC_URL, commitment=Confirmed) as rpc:

        # ── Step 3: Fund wallets ───────────────────────────────────────────────
        print("[ 2/4 ] Funding wallets")
        await _ensure_funded(rpc, hw, "hardware")
        await _ensure_funded(rpc, owner, "owner   ")
        print()

        pid = Pubkey.from_string(PROGRAM_ID)

        # ── Step 4: Initialize agent PDA ──────────────────────────────────────
        print("[ 3/4 ] Agent PDA")
        agent_pda, _ = _find_agent_pda(pid, owner.pubkey)
        if await _account_exists(rpc, agent_pda):
            print(f"  ✓ Already exists: {agent_pda}")
        else:
            print(f"  → Initializing agent PDA {agent_pda}...")
            async with AuxinProgramClient.connect(rpc_url=RPC_URL, program_id=PROGRAM_ID) as client:
                sig = await client.initialize_agent(
                    owner_wallet=owner,
                    hardware_wallet=hw,
                    compute_budget_lamports=COMPUTE_BUDGET_LAMPORTS,
                )
            print(f"  ✓ Initialized. tx: {_explorer_tx(sig)}")
        print()

        # ── Step 5: Whitelist hardware wallet as provider ─────────────────────
        print("[ 4/4 ] Provider whitelist")
        provider_pda, _ = _find_provider_pda(pid, hw.pubkey)
        if await _account_exists(rpc, provider_pda):
            print(f"  ✓ Already whitelisted: {hw.pubkey}")
        else:
            print(f"  → Whitelisting hardware wallet as provider...")
            async with AuxinProgramClient.connect(rpc_url=RPC_URL, program_id=PROGRAM_ID) as client:
                sig = await client.add_provider(
                    owner_wallet=owner,
                    provider_pubkey=hw.pubkey,
                )
            print(f"  ✓ Whitelisted. tx: {_explorer_tx(sig)}")
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Setup complete — ready to run:  make demo")
    print()
    print(f"  Hardware wallet : {_explorer_addr(hw.pubkey)}")
    print(f"  Owner wallet    : {_explorer_addr(owner.pubkey)}")
    print(f"  Agent PDA       : {_explorer_addr(_find_agent_pda(pid, owner.pubkey)[0])}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()


if __name__ == "__main__":
    asyncio.run(main())

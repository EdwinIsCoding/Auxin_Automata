"""Hardware wallet — wraps a solders Keypair with async Solana RPC methods."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey

log = structlog.get_logger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000


class HardwareWallet:
    """
    Lightweight hardware wallet backed by a solders Keypair.

    Keypairs are persisted as a JSON array of 64 bytes (the standard Solana CLI
    format) at the path supplied to ``load_or_create``.

    WARNING: Never commit the keypair file to version control.

    Example
    -------
    ::

        wallet = HardwareWallet.load_or_create("~/.config/auxin/hardware.json")
        balance = await wallet.get_balance(rpc_url)
    """

    def __init__(self, keypair: Keypair) -> None:
        self._keypair = keypair

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    def load_or_create(cls, path: Path | str) -> HardwareWallet:
        """Load an existing keypair from *path*, or generate and persist a new one."""
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            raw: list[int] = json.loads(path.read_text())
            keypair = Keypair.from_bytes(bytes(raw))
            log.info("wallet.loaded", pubkey=str(keypair.pubkey()), path=str(path))
        else:
            keypair = Keypair()
            path.write_text(json.dumps(list(bytes(keypair))))
            path.chmod(0o600)  # owner read/write only — private key must not be world-readable
            log.info("wallet.created", pubkey=str(keypair.pubkey()), path=str(path))

        return cls(keypair)

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def pubkey(self) -> Pubkey:
        """The hardware device's Solana public key."""
        return self._keypair.pubkey()

    @property
    def solders_keypair(self) -> Keypair:
        """
        Raw solders Keypair — exposed for direct use by program clients in Phase 2A.

        The AuxinProgramClient uses this to sign Anchor-generated transactions.
        """
        return self._keypair

    # ── Signing ───────────────────────────────────────────────────────────────

    def sign_transaction(self, tx: Any) -> Any:
        """
        Sign *tx* with the hardware wallet's keypair and return it.

        Accepts any transaction object with a ``sign(signers)`` method (solana-py
        legacy Transaction).  For solders VersionedTransaction, use
        ``solders_keypair`` directly with the Anchor client in Phase 2A.
        """
        if hasattr(tx, "sign"):
            tx.sign([self._keypair])
        return tx

    # ── Network (async) ───────────────────────────────────────────────────────

    async def get_balance(self, rpc_url: str) -> int:
        """Return the wallet's current balance in lamports."""
        async with AsyncClient(rpc_url) as client:
            response = await client.get_balance(self.pubkey)
            balance: int = response.value
            log.debug("wallet.balance", pubkey=str(self.pubkey), lamports=balance)
            return balance

    async def request_airdrop(self, rpc_url: str, sol: float) -> str:
        """
        Request a Devnet airdrop of *sol* SOL.

        Returns the transaction signature string.  Only works on Devnet/Testnet.
        """
        lamports = int(sol * LAMPORTS_PER_SOL)
        async with AsyncClient(rpc_url) as client:
            response = await client.request_airdrop(self.pubkey, lamports)
            sig = str(response.value)
            log.info("wallet.airdrop", pubkey=str(self.pubkey), sol=sol, signature=sig)
            return sig

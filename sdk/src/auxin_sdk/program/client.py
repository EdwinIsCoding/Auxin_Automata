"""
AuxinProgramClient — high-level async client for agentic_hardware_bridge.

Wraps the Anchor program using anchorpy.  The IDL is loaded from:
  1. The path passed to __init__ (e.g. after anchor build)
  2. The bundled idl.json shipped with the SDK as fallback

Usage
-----
::

    from auxin_sdk.program import AuxinProgramClient
    from auxin_sdk.wallet import HardwareWallet

    owner  = HardwareWallet.load_or_create("~/.config/auxin/owner.json")
    hw     = HardwareWallet.load_or_create("~/.config/auxin/hardware.json")

    async with AuxinProgramClient.connect(rpc_url=os.environ["HELIUS_RPC_URL"]) as client:
        sig = await client.initialize_agent(
            owner_wallet=owner,
            hardware_wallet=hw,
            compute_budget_lamports=500_000_000,  # 0.5 SOL
        )
        print("init agent tx:", sig)

        sig = await client.stream_payment(
            hw_wallet=hw,
            owner_pubkey=owner.pubkey,
            provider_pubkey=provider_pubkey,
            amount_lamports=10_000,
        )
        print("payment tx:", sig)

        sig = await client.log_compliance(
            hw_wallet=hw,
            owner_pubkey=owner.pubkey,
            telemetry_hash="a" * 64,
            severity=2,
            reason_code=0x0001,
        )
        print("compliance tx:", sig)
"""

from __future__ import annotations

import hashlib
import json
import struct
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import structlog
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.transaction import VersionedTransaction
from solders.message import MessageV0

from auxin_sdk.wallet import HardwareWallet

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_IDL_BUNDLED = Path(__file__).parent / "idl.json"
_IDL_BUILT = (
    Path(__file__).parents[5]  # repo root
    / "programs/target/idl/agentic_hardware_bridge.json"
)

LAMPORTS_PER_SOL = 1_000_000_000


# ── Discriminator helpers ─────────────────────────────────────────────────────

def _ix_disc(name: str) -> bytes:
    """Compute the 8-byte Anchor instruction discriminator."""
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


def _acc_disc(name: str) -> bytes:
    """Compute the 8-byte Anchor account discriminator."""
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


# Pre-computed discriminators (validated against the program source)
_DISC = {
    "initialize_agent":          _ix_disc("initialize_agent"),
    "stream_compute_payment":    _ix_disc("stream_compute_payment"),
    "log_compliance_event":      _ix_disc("log_compliance_event"),
    "update_provider_whitelist": _ix_disc("update_provider_whitelist"),
}


# ── Borsh serialisation helpers ───────────────────────────────────────────────

def _pack_pubkey(pk: Pubkey) -> bytes:
    return bytes(pk)


def _pack_u64(v: int) -> bytes:
    return struct.pack("<Q", v)


def _pack_u16(v: int) -> bytes:
    return struct.pack("<H", v)


def _pack_u8(v: int) -> bytes:
    return struct.pack("<B", v)


def _pack_bool(v: bool) -> bytes:
    return b"\x01" if v else b"\x00"


def _pack_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _pack_enum_unit(variant_idx: int) -> bytes:
    """Serialize a C-style Anchor enum variant (Add=0, Remove=1)."""
    return struct.pack("<I", variant_idx)


# ── PDA derivation ────────────────────────────────────────────────────────────

def _find_agent_pda(program_id: Pubkey, owner: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([b"agent", bytes(owner)], program_id)


def _find_provider_pda(program_id: Pubkey, provider: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([b"provider", bytes(provider)], program_id)


def _find_compliance_log_pda(
    program_id: Pubkey, agent: Pubkey, slot: int
) -> tuple[Pubkey, int]:
    slot_bytes = struct.pack("<Q", slot)
    return Pubkey.find_program_address(
        [b"log", bytes(agent), slot_bytes], program_id
    )


# ── Client ────────────────────────────────────────────────────────────────────

class AuxinProgramClient:
    """
    High-level async client for the agentic_hardware_bridge Anchor program.

    The client sends VersionedTransactions using Solana's v0 message format.
    Every method returns the confirmed transaction signature string.
    """

    def __init__(self, rpc_client: AsyncClient, program_id: Pubkey) -> None:
        self._rpc = rpc_client
        self.program_id = program_id

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    @asynccontextmanager
    async def connect(
        cls,
        rpc_url: str,
        program_id: Pubkey | str | None = None,
        idl_path: Path | str | None = None,
    ) -> AsyncIterator[AuxinProgramClient]:
        """
        Async context manager.  Resolves program_id from:
          1. The explicit argument
          2. /programs/deployed.json
          3. The bundled IDL
        """
        pid = cls._resolve_program_id(program_id, idl_path)
        async with AsyncClient(rpc_url, commitment=Confirmed) as rpc:
            yield cls(rpc, pid)

    @staticmethod
    def _resolve_program_id(
        explicit: Pubkey | str | None, idl_path: Path | str | None
    ) -> Pubkey:
        if explicit is not None:
            return Pubkey.from_string(str(explicit)) if isinstance(explicit, str) else explicit

        # Try deployed.json
        deployed = (
            Path(__file__).parents[5] / "programs/deployed.json"
        )
        if deployed.exists():
            data = json.loads(deployed.read_text())
            return Pubkey.from_string(data["program_id"])

        # Try built IDL
        if _IDL_BUILT.exists():
            idl = json.loads(_IDL_BUILT.read_text())
            return Pubkey.from_string(idl["address"])

        # Fall back to bundled IDL
        idl = json.loads(_IDL_BUNDLED.read_text())
        return Pubkey.from_string(idl["address"])

    # ── Low-level tx helper ───────────────────────────────────────────────────

    async def _send(
        self,
        ix: Instruction,
        signers: list[HardwareWallet],
    ) -> str:
        """Build, sign, and send a VersionedTransaction.  Returns signature."""
        bh_resp = await self._rpc.get_latest_blockhash(commitment=Confirmed)
        blockhash = Hash.from_string(str(bh_resp.value.blockhash))

        payer_kp = signers[0].solders_keypair
        keypairs = [w.solders_keypair for w in signers]

        msg = MessageV0.try_compile(
            payer=payer_kp.pubkey(),
            instructions=[ix],
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash,
        )
        tx = VersionedTransaction(msg, keypairs)

        resp = await self._rpc.send_transaction(
            tx,
            opts={"skip_preflight": False, "preflight_commitment": Confirmed},
        )
        sig = str(resp.value)

        # Confirm
        await self._rpc.confirm_transaction(sig, commitment=Confirmed)
        log.info(
            "program.tx_confirmed",
            signature=sig,
            program_id=str(self.program_id),
        )
        return sig

    # ── initialize_agent ──────────────────────────────────────────────────────

    async def initialize_agent(
        self,
        owner_wallet: HardwareWallet,
        hardware_wallet: HardwareWallet,
        compute_budget_lamports: int,
    ) -> str:
        """
        Create a HardwareAgent PDA.

        Signed by owner (pays rent + funds PDA with compute_budget_lamports).
        Returns confirmed transaction signature.
        """
        owner = owner_wallet.pubkey
        agent_pda, _ = _find_agent_pda(self.program_id, owner)

        data = (
            _DISC["initialize_agent"]
            + _pack_pubkey(hardware_wallet.pubkey)
            + _pack_u64(compute_budget_lamports)
        )

        ix = Instruction(
            program_id=self.program_id,
            data=bytes(data),
            accounts=[
                AccountMeta(pubkey=agent_pda,      is_signer=False, is_writable=True),
                AccountMeta(pubkey=owner,           is_signer=True,  is_writable=True),
                AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
            ],
        )

        sig = await self._send(ix, [owner_wallet])
        log.info(
            "agent.initialized",
            agent=str(agent_pda),
            owner=str(owner),
            compute_budget_lamports=compute_budget_lamports,
            signature=sig,
        )
        return sig

    # ── stream_payment ────────────────────────────────────────────────────────

    async def stream_payment(
        self,
        hw_wallet: HardwareWallet,
        owner_pubkey: Pubkey,
        provider_pubkey: Pubkey,
        amount_lamports: int,
    ) -> str:
        """
        Stream a compute payment from the agent PDA to a whitelisted provider.

        Signed by the hardware wallet (autonomous — hardware signs, not owner).
        Returns confirmed transaction signature.
        """
        agent_pda, _ = _find_agent_pda(self.program_id, owner_pubkey)
        provider_record_pda, _ = _find_provider_pda(self.program_id, provider_pubkey)

        data = _DISC["stream_compute_payment"] + _pack_u64(amount_lamports)

        ix = Instruction(
            program_id=self.program_id,
            data=bytes(data),
            accounts=[
                AccountMeta(pubkey=agent_pda,           is_signer=False, is_writable=True),
                AccountMeta(pubkey=hw_wallet.pubkey,    is_signer=True,  is_writable=True),
                AccountMeta(pubkey=provider_pubkey,     is_signer=False, is_writable=True),
                AccountMeta(pubkey=provider_record_pda, is_signer=False, is_writable=True),
                AccountMeta(pubkey=SYS_PROGRAM_ID,      is_signer=False, is_writable=False),
            ],
        )

        sig = await self._send(ix, [hw_wallet])
        log.info(
            "payment.streamed",
            agent=str(agent_pda),
            provider=str(provider_pubkey),
            amount_lamports=amount_lamports,
            signature=sig,
        )
        return sig

    # ── log_compliance ────────────────────────────────────────────────────────

    async def log_compliance(
        self,
        hw_wallet: HardwareWallet,
        owner_pubkey: Pubkey,
        telemetry_hash: str,
        severity: int,
        reason_code: int,
    ) -> str:
        """
        Write an immutable ComplianceLog PDA.

        Signed by the hardware wallet.  Never rate-limited or budget-blocked.
        Returns confirmed transaction signature.
        """
        if len(telemetry_hash) > 64:
            raise ValueError(f"telemetry_hash exceeds 64 bytes: {len(telemetry_hash)}")
        if severity not in (0, 1, 2, 3):
            raise ValueError(f"severity must be 0-3, got {severity}")

        agent_pda, _ = _find_agent_pda(self.program_id, owner_pubkey)

        # Derive the compliance log PDA using the current slot
        slot_resp = await self._rpc.get_slot(commitment=Confirmed)
        slot = slot_resp.value
        log_pda, _ = _find_compliance_log_pda(self.program_id, agent_pda, slot)

        data = (
            _DISC["log_compliance_event"]
            + _pack_string(telemetry_hash)
            + _pack_u8(severity)
            + _pack_u16(reason_code)
            + struct.pack("<Q", slot)  # slot: u64 le — used as PDA seed
        )

        ix = Instruction(
            program_id=self.program_id,
            data=bytes(data),
            accounts=[
                AccountMeta(pubkey=agent_pda,        is_signer=False, is_writable=False),
                AccountMeta(pubkey=hw_wallet.pubkey, is_signer=True,  is_writable=True),
                AccountMeta(pubkey=log_pda,          is_signer=False, is_writable=True),
                AccountMeta(pubkey=SYS_PROGRAM_ID,   is_signer=False, is_writable=False),
            ],
        )

        sig = await self._send(ix, [hw_wallet])
        log.info(
            "compliance.logged",
            agent=str(agent_pda),
            log_pda=str(log_pda),
            severity=severity,
            reason_code=hex(reason_code),
            signature=sig,
        )
        return sig

    # ── update_provider_whitelist ─────────────────────────────────────────────

    async def add_provider(
        self,
        owner_wallet: HardwareWallet,
        provider_pubkey: Pubkey,
    ) -> str:
        """Add a provider to the agent's whitelist.  Signed by owner."""
        return await self._whitelist_update(owner_wallet, provider_pubkey, add=True)

    async def remove_provider(
        self,
        owner_wallet: HardwareWallet,
        provider_pubkey: Pubkey,
    ) -> str:
        """Remove a provider from the agent's whitelist.  Signed by owner."""
        return await self._whitelist_update(owner_wallet, provider_pubkey, add=False)

    async def _whitelist_update(
        self,
        owner_wallet: HardwareWallet,
        provider_pubkey: Pubkey,
        add: bool,
    ) -> str:
        owner = owner_wallet.pubkey
        agent_pda, _ = _find_agent_pda(self.program_id, owner)

        # WhitelistAction::Add = 0, Remove = 1
        data = (
            _DISC["update_provider_whitelist"]
            + _pack_pubkey(provider_pubkey)
            + _pack_enum_unit(0 if add else 1)
        )

        ix = Instruction(
            program_id=self.program_id,
            data=bytes(data),
            accounts=[
                AccountMeta(pubkey=agent_pda, is_signer=False, is_writable=True),
                AccountMeta(pubkey=owner,     is_signer=True,  is_writable=False),
            ],
        )

        sig = await self._send(ix, [owner_wallet])
        action = "added" if add else "removed"
        log.info(
            "whitelist.updated",
            agent=str(agent_pda),
            provider=str(provider_pubkey),
            action=action,
            signature=sig,
        )
        return sig

    # ── PDA query helpers ─────────────────────────────────────────────────────

    def agent_pda(self, owner: Pubkey) -> Pubkey:
        pda, _ = _find_agent_pda(self.program_id, owner)
        return pda

    def provider_pda(self, provider: Pubkey) -> Pubkey:
        pda, _ = _find_provider_pda(self.program_id, provider)
        return pda

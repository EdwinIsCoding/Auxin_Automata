"""CloakProvider — private M2M payments via cloak.ag's shield pool.

Architecture
------------
Cloak uses a UTXO-based shield pool with Groth16 ZK proofs.  Each payment
deposits SOL into the pool as an unlinkable UTXO commitment.  The recipient
detects incoming UTXOs using their viewing key and withdraws via Cloak's
relay service — the on-chain deposit reveals neither the sender-payee link
nor the payment pattern.

Because the Cloak SDK is TypeScript only (@cloak.dev/sdk), this module uses
a subprocess bridge: Python calls a Node.js script (``cloak_bridge/deposit.mjs``)
that performs the ZK proof generation and Solana transaction submission.

Fallback
--------
If the Cloak bridge fails for any reason (Node.js not installed, SDK error,
relayer down, timeout), the provider falls back to DirectProvider with a
warning log.  The demo must never stall on a privacy provider failure.

Compliance
----------
Compliance events are NEVER routed through CloakProvider.  Compliance hashes
are public on-chain evidence; only M2M streaming payments are privatised.
Payment details are private but auditable via the Cloak viewing key — see
``docs/privacy-cloak.md`` for the full compliance story.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import structlog

from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider
from auxin_sdk.wallet import HardwareWallet

log = structlog.get_logger(__name__)

# Path to the Node.js bridge scripts (shipped alongside this module).
_BRIDGE_DIR = Path(__file__).parent / "cloak_bridge"
_DEPOSIT_SCRIPT = _BRIDGE_DIR / "deposit.mjs"

# Subprocess timeout — generous to allow for ZK proof generation + Solana confirmation.
_SUBPROCESS_TIMEOUT_S = 60.0


class CloakProvider(PrivacyProvider):
    """Route payments through cloak.ag's ZK shield pool.

    Constructor Parameters
    ----------------------
    rpc_url:
        Solana RPC endpoint (Helius/QuickNode recommended).
    fallback:
        Optional DirectProvider to use when the Cloak bridge fails.
        If ``None``, errors propagate to the caller.
    cloak_program_id:
        Cloak program address.  Defaults to the mainnet/devnet deployment.
    relay_url:
        Cloak relay service URL.  ``None`` uses the SDK built-in default.

    Viewing Key Support
    -------------------
    Each payment result includes the UTXO private key in ``metadata`` (hex
    encoded).  The operator should store these securely.  An auditor with
    the viewing key derived from the UTXO private key can verify the full
    payment history without the operator disclosing it publicly.  See
    ``cloak_bridge/keygen.mjs`` and ``docs/privacy-cloak.md``.
    """

    # cloak.ag program ID — same on mainnet and devnet
    DEFAULT_PROGRAM_ID = "zh1eLd6rSphLejbFfJEneUwzHRfMKxgzrgkfwA6qRkW"

    def __init__(
        self,
        rpc_url: str,
        *,
        fallback: PrivacyProvider | None = None,
        cloak_program_id: str | None = None,
        relay_url: str | None = None,
    ) -> None:
        self._rpc_url = rpc_url
        self._fallback = fallback
        self._program_id = cloak_program_id or self.DEFAULT_PROGRAM_ID
        self._relay_url = relay_url
        self._submitted: set[str] = set()

    # ── PrivacyProvider interface ─────────────────────────────────────────────

    async def send_payment(
        self,
        wallet: HardwareWallet,
        owner_pubkey: Any,
        provider_pubkey: Any,
        lamports: int,
        *,
        idempotency_key: str,
    ) -> PaymentResult:
        if idempotency_key in self._submitted:
            log.warning("cloak_provider.idempotent_skip", key=idempotency_key)
            return PaymentResult(
                tx_signature=None,
                privacy_provider="cloak",
                is_private=True,
                confirmation_slot=None,
                metadata={"skipped": "duplicate"},
            )

        try:
            result = await self._deposit(wallet, provider_pubkey, lamports)
            self._submitted.add(idempotency_key)
            return PaymentResult(
                tx_signature=result["signature"],
                privacy_provider="cloak",
                is_private=True,
                confirmation_slot=result.get("confirmation_slot"),
                metadata={
                    "utxo_commitment": result.get("utxo_commitment", ""),
                    # The UTXO private key allows the recipient to withdraw.
                    # Stored in metadata for operator records — never published.
                    "utxo_private_key_hex": result.get("utxo_private_key_hex", ""),
                    "provider_pubkey": str(provider_pubkey),
                },
            )
        except Exception as exc:
            if self._fallback is not None:
                log.warning(
                    "cloak_provider.fallback_to_direct",
                    error=str(exc),
                    lamports=lamports,
                )
                return await self._fallback.send_payment(
                    wallet=wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    lamports=lamports,
                    idempotency_key=idempotency_key,
                )
            raise

    # ── Subprocess bridge ─────────────────────────────────────────────────────

    async def _deposit(
        self,
        wallet: HardwareWallet,
        provider_pubkey: Any,
        lamports: int,
    ) -> dict[str, Any]:
        """Call the Node.js deposit script and return the parsed result.

        Raises RuntimeError if the subprocess exits non-zero or times out.
        """
        # Serialize the wallet's 64-byte keypair for the Node.js script.
        keypair_bytes = bytes(wallet.solders_keypair)
        input_data = json.dumps({
            "rpc_url": self._rpc_url,
            "wallet_secret_b64": base64.b64encode(keypair_bytes).decode(),
            "provider_pubkey": str(provider_pubkey),
            "amount_lamports": lamports,
            "program_id": self._program_id,
            "relay_url": self._relay_url,
        })

        try:
            proc = await asyncio.create_subprocess_exec(
                "node",
                str(_DEPOSIT_SCRIPT),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_data.encode()),
                timeout=_SUBPROCESS_TIMEOUT_S,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Node.js not found. CloakProvider requires Node >=20 installed. "
                "Install it or set AUXIN_PRIVACY=direct to skip Cloak."
            )
        except TimeoutError:
            raise RuntimeError(
                f"Cloak deposit timed out after {_SUBPROCESS_TIMEOUT_S}s. "
                "The relayer may be unreachable or ZK proof generation stalled."
            )

        if proc.returncode != 0:
            err_msg = stderr.decode().strip() if stderr else "unknown error"
            # Try to extract structured error from JSON stderr
            try:
                err_data = json.loads(err_msg)
                err_msg = err_data.get("error", err_msg)
            except (json.JSONDecodeError, KeyError):
                pass
            raise RuntimeError(f"Cloak deposit failed: {err_msg}")

        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Cloak bridge returned invalid JSON: {stdout.decode()[:200]}"
            ) from exc

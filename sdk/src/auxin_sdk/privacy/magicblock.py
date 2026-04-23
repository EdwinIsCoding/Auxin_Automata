"""MagicBlockProvider — private M2M payments via MagicBlock Private Ephemeral Rollups.

Architecture
------------
MagicBlock's Private Ephemeral Rollups (PERs) run inside TEEs (Trusted Execution
Environments).  Users delegate SPL tokens into the rollup; individual transfers
are settled privately within it.  A crank periodically settles balances back to
Solana with no traceable per-payment link on the public ledger.

API flow
--------
The REST API at ``https://payments.magicblock.app`` builds **unsigned** Solana
transactions.  This module:

1. Calls ``POST /v1/spl/transfer`` to get an unsigned transaction for a payment.
2. Signs the transaction with the hardware wallet keypair (solders).
3. Submits the signed transaction to Solana (or MagicBlock's rollup validator
   indicated by the API's ``sendTo`` field).
4. Returns a ``PaymentResult`` with ``is_private=True, privacy_provider="magicblock"``.

Budget pre-delegation
---------------------
``delegate_budget(wallet, lamports)`` deposits wSOL into the rollup once via
``POST /v1/spl/deposit``.  Subsequent ``send_payment()`` calls draw from this
pool, avoiding a separate delegation round-trip per micro-payment.  Pre-delegated
funds remain in the TEE until explicitly withdrawn or settled by the crank.

Trade-off: pre-delegation is faster (no on-chain deposit per payment) but
means a batch of lamports is in the TEE before it is consumed.  Set the
pre-delegation amount to ~1 hour of expected payment volume.

Compliance
----------
MagicBlock enforces AML compliance at the API layer.  Every payment request is
screened via Range for sanctions, counterparty risk, and behavioural signals.
Transactions failing AML checks are rejected before execution — M2M autonomous
payments are AML-screened without any additional operator-side infrastructure.
See ``docs/privacy-magicblock.md`` for the full compliance story.

Fallback
--------
If the MagicBlock API is unreachable or returns an error, the provider falls
back to the injected ``fallback`` PrivacyProvider (typically DirectProvider)
with a warning log.  The demo never stalls on a privacy provider failure.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import httpx
import structlog
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts

from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider
from auxin_sdk.wallet import HardwareWallet

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Canonical MagicBlock Private Payments API
_DEFAULT_API_URL = "https://payments.magicblock.app"

# wSOL mint — used when making native-SOL-equivalent private payments.
# The operator's wSOL ATA is funded via delegate_budget(); payments draw from it.
_WSOL_MINT = "So11111111111111111111111111111111111111112"

# HTTP + Solana confirmation timeout per operation.
_HTTP_TIMEOUT_S = 30.0
_CONFIRM_TIMEOUT_S = 90.0


class MagicBlockProvider(PrivacyProvider):
    """Route payments through MagicBlock's Private Ephemeral Rollup API.

    Constructor Parameters
    ----------------------
    rpc_url:
        Solana RPC endpoint used to submit signed transactions.  MagicBlock
        API responses may include a ``sendTo`` URL; when present that takes
        precedence for submission (it may point to the rollup validator).
    api_url:
        MagicBlock Private Payments API base URL.  Defaults to
        ``https://payments.magicblock.app``.
    api_key:
        Optional API key passed as ``Authorization: Bearer <key>``.  Contact
        MagicBlock to obtain one for production use.
    mint:
        SPL token mint for payments.  Defaults to the wSOL mint
        (``So11111111111111111111111111111111111111112``).
    cluster:
        Solana cluster label forwarded to the API (``devnet`` or
        ``mainnet-beta``).  Defaults to ``devnet``.
    fallback:
        Optional PrivacyProvider to use when the MagicBlock API fails.
        If ``None``, errors propagate to the caller.

    AML Compliance
    --------------
    Every API call is screened by MagicBlock via Range for OFAC sanctions,
    counterparty risk, and behavioural signals.  Transactions that fail AML
    checks are rejected at the API layer with HTTP 400 before any on-chain
    action is taken.  This gives autonomous M2M payments AML coverage without
    operator-side infrastructure.  See ``docs/privacy-magicblock.md``.
    """

    def __init__(
        self,
        rpc_url: str,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        mint: str | None = None,
        cluster: str = "devnet",
        fallback: PrivacyProvider | None = None,
    ) -> None:
        self._rpc_url = rpc_url
        self._api_url = (api_url or _DEFAULT_API_URL).rstrip("/")
        self._api_key = api_key
        self._mint = mint or _WSOL_MINT
        self._cluster = cluster
        self._fallback = fallback
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
        """Send a private micro-payment via MagicBlock's ephemeral rollup.

        Calls ``POST /v1/spl/transfer``, signs the returned unsigned
        transaction, submits it, and returns ``is_private=True``.
        """
        if idempotency_key in self._submitted:
            log.warning("magicblock_provider.idempotent_skip", key=idempotency_key)
            return PaymentResult(
                tx_signature=None,
                privacy_provider="magicblock",
                is_private=True,
                confirmation_slot=None,
                metadata={"skipped": "duplicate"},
            )

        try:
            result = await self._transfer(wallet, owner_pubkey, provider_pubkey, lamports)
            self._submitted.add(idempotency_key)
            return PaymentResult(
                tx_signature=result["signature"],
                privacy_provider="magicblock",
                is_private=True,
                confirmation_slot=result.get("slot"),
                metadata={
                    "provider_pubkey": str(provider_pubkey),
                    "mint": self._mint,
                    "cluster": self._cluster,
                },
            )
        except Exception as exc:
            if self._fallback is not None:
                log.warning(
                    "magicblock_provider.fallback_to_direct",
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

    # ── Pre-delegation ────────────────────────────────────────────────────────

    async def delegate_budget(
        self,
        wallet: HardwareWallet,
        lamports: int,
    ) -> str:
        """Deposit *lamports* of wSOL into the MagicBlock rollup.

        Call this once to pre-fund the rollup pool.  Subsequent ``send_payment``
        calls draw from this pool without a per-payment deposit round-trip.

        Returns the Solana deposit transaction signature.

        Trade-off
        ---------
        Pre-delegation is faster (one on-chain tx vs. one per payment) but
        means the specified lamport amount is in the TEE until consumed or
        withdrawn.  Set the amount to ~1 hour of expected payment volume and
        top up periodically.
        """
        body: dict[str, Any] = {
            "owner": str(wallet.pubkey),
            "amount": lamports,
            "mint": self._mint,
            "cluster": self._cluster,
            "initIfMissing": True,
            "initVaultIfMissing": True,
        }

        log.info(
            "magicblock_provider.delegate_budget",
            owner=str(wallet.pubkey),
            lamports=lamports,
            mint=self._mint,
        )

        api_resp = await self._post("/v1/spl/deposit", body)
        tx_b64: str = api_resp["transactionBase64"]
        send_to: str | None = api_resp.get("sendTo") or self._rpc_url

        result = await self._sign_and_send(wallet, tx_b64, send_to)
        log.info(
            "magicblock_provider.budget_delegated",
            signature=result["signature"],
            lamports=lamports,
        )
        return result["signature"]

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _transfer(
        self,
        wallet: HardwareWallet,
        owner_pubkey: Any,
        provider_pubkey: Any,
        lamports: int,
    ) -> dict[str, Any]:
        """Build, sign, and submit a private SPL transfer transaction."""
        body: dict[str, Any] = {
            "owner": str(owner_pubkey),
            "destination": str(provider_pubkey),
            "amount": lamports,
            "mint": self._mint,
            "cluster": self._cluster,
            "privacy": "private",
        }

        api_resp = await self._post("/v1/spl/transfer", body)
        tx_b64: str = api_resp["transactionBase64"]
        send_to: str | None = api_resp.get("sendTo") or self._rpc_url

        return await self._sign_and_send(wallet, tx_b64, send_to)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST to the MagicBlock API and return the parsed JSON response.

        Raises ``RuntimeError`` on HTTP 4xx / 5xx or network errors.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        url = f"{self._api_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"MagicBlock API unreachable at {url}: {exc}"
            ) from exc

        if resp.status_code >= 400:
            # AML rejection comes as 400 with a JSON body explaining why
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise RuntimeError(
                f"MagicBlock API error {resp.status_code}: {detail}"
            )

        return resp.json()

    async def _sign_and_send(
        self,
        wallet: HardwareWallet,
        tx_b64: str,
        submit_url: str,
    ) -> dict[str, Any]:
        """Sign a base64-encoded unsigned transaction and submit it to Solana.

        Returns a dict with ``signature`` and optionally ``slot``.
        """
        tx_bytes = base64.b64decode(tx_b64)
        signed_raw = _sign_transaction_bytes(tx_bytes, wallet)

        async with AsyncClient(submit_url) as client:
            try:
                resp = await asyncio.wait_for(
                    client.send_raw_transaction(
                        signed_raw,
                        opts=TxOpts(
                            skip_preflight=False,
                            preflight_commitment="confirmed",
                        ),
                    ),
                    timeout=_CONFIRM_TIMEOUT_S,
                )
            except TimeoutError as exc:
                raise RuntimeError(
                    f"MagicBlock transaction submission timed out after "
                    f"{_CONFIRM_TIMEOUT_S}s"
                ) from exc

        sig = str(resp.value)
        log.info(
            "magicblock_provider.tx_submitted",
            signature=sig,
            submit_url=submit_url,
        )
        return {"signature": sig}


# ── Transaction signing helper ────────────────────────────────────────────────


def _sign_transaction_bytes(tx_bytes: bytes, wallet: HardwareWallet) -> bytes:
    """Sign a serialized unsigned Solana transaction.

    Tries VersionedTransaction first (modern format).  Falls back to legacy
    ``solana.transaction.Transaction`` if deserialization fails.

    Returns the signed raw transaction bytes ready for ``send_raw_transaction``.
    """
    keypair = wallet.solders_keypair

    # ── Versioned transaction (preferred) ─────────────────────────────────────
    try:
        from solders.transaction import VersionedTransaction  # type: ignore[import]

        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed = VersionedTransaction([keypair], tx.message)
        return bytes(signed)
    except Exception:
        pass

    # ── Legacy transaction ────────────────────────────────────────────────────
    try:
        from solana.transaction import Transaction as LegacyTx  # type: ignore[import]

        tx = LegacyTx.deserialize(tx_bytes)
        tx.sign([keypair])
        return tx.serialize()
    except Exception as exc:
        raise RuntimeError(
            f"Failed to deserialize MagicBlock transaction: {exc}"
        ) from exc

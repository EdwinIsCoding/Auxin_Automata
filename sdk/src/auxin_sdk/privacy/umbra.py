"""UmbraProvider — private M2M payments via Umbra's unified mixer pool.

Architecture
------------
Umbra is a financial privacy layer for Solana built on Arcium's MPC network.
It provides a unified mixer pool backed by Merkle trees and Groth16 ZK proofs
that breaks the on-chain link between deposits and withdrawals.

Since the Umbra SDK (``@umbra-privacy/sdk``) is TypeScript, this module
communicates with a lightweight Express sidecar (``/services/umbra-bridge/``)
over HTTP on localhost.  The sidecar handles ZK proof generation and Solana
transaction construction; this module handles orchestration, idempotency,
and fallback.

Payment flow
------------
1. ``POST /deposit`` to the sidecar — creates a self-claimable UTXO in the
   mixer pool from the hardware wallet's public balance.
2. After the protocol's mixing delay, the recipient claims the UTXO via the
   sidecar's ``POST /withdraw`` endpoint.
3. Individual micro-payments are indistinguishable in the pool — an observer
   sees deposits and withdrawals but cannot link them.

Selective disclosure
--------------------
Operators generate time-scoped viewing keys from their Master Viewing Key
(derived deterministically from the wallet signature).  Sharing a viewing key
with an auditor grants read-only access to mixer activity for that time scope
without exposing spending authority.  See ``docs/privacy-umbra.md``.

Fallback
--------
If the sidecar is unreachable or returns an error, the provider falls back to
the injected ``fallback`` PrivacyProvider (typically DirectProvider) with a
warning log.  The demo never stalls on a privacy provider failure.

Program IDs
-----------
Mainnet: ``UMBRAD2ishebJTcgCLkTkNUx1v3GyoAgpTRPeWoLykh``
Devnet:  ``DSuKkyqGVGgo4QtPABfxKJKygUDACbUhirnuv63mEpAJ``
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider
from auxin_sdk.wallet import HardwareWallet

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_SIDECAR_URL = "http://localhost:3002"

# wSOL mint — used for native-SOL-equivalent private payments
_WSOL_MINT = "So11111111111111111111111111111111111111112"

_HTTP_TIMEOUT_S = 90.0  # ZK proof generation can take several seconds


class UmbraProvider(PrivacyProvider):
    """Route payments through Umbra's unified mixer pool via the sidecar.

    Constructor Parameters
    ----------------------
    sidecar_url:
        URL of the umbra-bridge Express sidecar.  Defaults to
        ``http://localhost:3002``.
    mint:
        SPL token mint for payments.  Defaults to the wSOL mint.
    fallback:
        Optional PrivacyProvider to use when the sidecar is unreachable.
        If ``None``, errors propagate to the caller.

    Selective Disclosure
    --------------------
    Call ``export_viewing_key(wallet, scope, ...)`` to derive a time-scoped
    Transaction Viewing Key from the Master Viewing Key.  Share this with an
    auditor — it grants read-only access to mixer activity for the specified
    scope (yearly/monthly/daily) without exposing spending authority.
    """

    def __init__(
        self,
        sidecar_url: str | None = None,
        *,
        mint: str | None = None,
        fallback: PrivacyProvider | None = None,
    ) -> None:
        self._sidecar_url = (sidecar_url or _DEFAULT_SIDECAR_URL).rstrip("/")
        self._mint = mint or _WSOL_MINT
        self._fallback = fallback
        self._submitted: set[str] = set()

    # ── Health check ──────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Return True if the umbra-bridge sidecar is reachable and healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._sidecar_url}/health")
                return resp.status_code == 200
        except httpx.RequestError:
            return False

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
        """Deposit lamports into Umbra's mixer pool as a self-claimable UTXO.

        The recipient (compute provider) claims the UTXO via the sidecar's
        ``/withdraw`` endpoint after the mixing delay.  From an on-chain
        observer's perspective, the deposit and claim are unlinkable.
        """
        if idempotency_key in self._submitted:
            log.warning("umbra_provider.idempotent_skip", key=idempotency_key)
            return PaymentResult(
                tx_signature=None,
                privacy_provider="umbra",
                is_private=True,
                confirmation_slot=None,
                metadata={"skipped": "duplicate"},
            )

        try:
            result = await self._deposit(wallet, provider_pubkey, lamports)
            self._submitted.add(idempotency_key)
            return PaymentResult(
                tx_signature=result.get("signature"),
                privacy_provider="umbra",
                is_private=True,
                confirmation_slot=None,
                metadata={
                    "utxo_commitment": result.get("utxo_commitment", ""),
                    "provider_pubkey": str(provider_pubkey),
                    "mint": self._mint,
                },
            )
        except Exception as exc:
            if self._fallback is not None:
                log.warning(
                    "umbra_provider.fallback_to_direct",
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

    # ── Selective disclosure ──────────────────────────────────────────────────

    async def export_viewing_key(
        self,
        wallet: HardwareWallet,
        scope: str = "master",
        *,
        mint: str | None = None,
        year: int | None = None,
        month: int | None = None,
        day: int | None = None,
    ) -> dict[str, str]:
        """Derive a time-scoped viewing key from the Master Viewing Key.

        Parameters
        ----------
        scope:
            ``"master"``, ``"yearly"``, ``"monthly"``, or ``"daily"``.
        mint, year, month, day:
            Narrowing parameters — required depending on scope.

        Returns
        -------
        dict with ``viewing_key`` (hex) and ``scope``.

        Auditor usage
        -------------
        Share the returned hex key with an auditor.  They can verify every
        UTXO in the mixer pool for the given scope without spending authority.
        """
        body: dict[str, Any] = {
            "keypair_bytes": list(bytes(wallet.solders_keypair)),
            "scope": scope,
        }
        if mint is not None:
            body["mint"] = mint
        if year is not None:
            body["year"] = year
        if month is not None:
            body["month"] = month
        if day is not None:
            body["day"] = day

        data = await self._post("/viewing-key", body)
        log.info(
            "umbra_provider.viewing_key_exported",
            scope=scope,
        )
        return {
            "viewing_key": data.get("viewing_key", ""),
            "scope": data.get("scope", scope),
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _deposit(
        self,
        wallet: HardwareWallet,
        provider_pubkey: Any,
        lamports: int,
    ) -> dict[str, Any]:
        """Call the sidecar's /deposit endpoint to create a UTXO."""
        body = {
            "keypair_bytes": list(bytes(wallet.solders_keypair)),
            "mint": self._mint,
            "amount": lamports,
            "destination_address": str(provider_pubkey),
        }
        return await self._post("/deposit", body)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST to the umbra-bridge sidecar and return parsed JSON.

        Raises ``RuntimeError`` on HTTP errors or network failures.
        """
        url = f"{self._sidecar_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
                resp = await client.post(url, json=body)
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Umbra sidecar unreachable at {url}: {exc}"
            ) from exc

        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise RuntimeError(
                f"Umbra sidecar error {resp.status_code}: {detail}"
            )

        return resp.json()

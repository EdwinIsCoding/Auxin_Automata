"""DirectProvider — public SOL transfer via the Auxin Anchor program.

This is the default AUXIN_PRIVACY=direct implementation.  It wraps
``AuxinProgramClient.stream_payment()`` with the same retry and idempotency
logic that the bridge previously applied inline, preserving identical
on-chain behaviour.

``is_private=False`` — the payer → payee link is visible on-chain.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider
from auxin_sdk.program.client import AuxinProgramClient
from auxin_sdk.wallet import HardwareWallet

log = structlog.get_logger(__name__)

_MAX_RETRIES = 3


class DirectProvider(PrivacyProvider):
    """Route payments directly through the Auxin Anchor program.

    Idempotency
    -----------
    An in-memory set tracks submitted ``idempotency_key`` values.  A second
    call with the same key returns ``PaymentResult(tx_signature=None, ...)``.
    The set lives for the lifetime of the Bridge process; it is not persisted.

    Retry behaviour
    ---------------
    On ``BlockhashNotFound`` or HTTP 429, the call is retried up to
    ``_MAX_RETRIES`` times with exponential back-off (matching the behaviour of
    the former ``_SubmissionLayer.stream_payment()``).  All other exceptions
    propagate immediately.
    """

    def __init__(self, client: AuxinProgramClient) -> None:
        self._client = client
        self._submitted: set[str] = set()

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
            log.warning("direct_provider.idempotent_skip", key=idempotency_key)
            return PaymentResult(
                tx_signature=None,
                privacy_provider="direct",
                is_private=False,
                confirmation_slot=None,
                metadata={"skipped": "duplicate"},
            )

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                sig = await self._client.stream_payment(
                    hw_wallet=wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    amount_lamports=lamports,
                )
                self._submitted.add(idempotency_key)
                log.info(
                    "direct_provider.payment_ok",
                    signature=sig,
                    amount_lamports=lamports,
                    attempt=attempt,
                )
                return PaymentResult(
                    tx_signature=sig,
                    privacy_provider="direct",
                    is_private=False,
                    confirmation_slot=None,
                    metadata={"attempt": attempt},
                )
            except Exception as exc:
                cause = exc.__cause__ or exc
                err_str = str(cause) or repr(exc)
                is_rate_limit = "429" in err_str or "Too Many Requests" in err_str
                is_blockhash = "BlockhashNotFound" in err_str
                if (is_blockhash or is_rate_limit) and attempt < _MAX_RETRIES:
                    log.warning(
                        "direct_provider.retry",
                        attempt=attempt,
                        error=err_str,
                    )
                    await asyncio.sleep(2.0 * attempt if is_rate_limit else 0.5 * attempt)
                    continue
                log.error("direct_provider.payment_failed", error=err_str, attempt=attempt)
                raise

        # Unreachable — the loop always returns or raises.
        return PaymentResult(  # pragma: no cover
            tx_signature=None,
            privacy_provider="direct",
            is_private=False,
            confirmation_slot=None,
            metadata={"error": "max_retries_exceeded"},
        )

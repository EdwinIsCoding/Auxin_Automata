"""PrivacyProvider ABC — payment-path abstraction for M2M Solana payments.

Architecture rule
-----------------
The active payment rail is selected SOLELY by the ``AUXIN_PRIVACY`` env var.
``Bridge._payment_worker`` calls ``privacy_provider.send_payment()`` without
knowing which concrete implementation is active — exactly the same pattern as
``AUXIN_SOURCE`` for the telemetry source.

Compliance events are NEVER routed through any PrivacyProvider.
See ``Bridge._compliance_worker`` for the canonical comment explaining why.

Implemented providers
---------------------
``DirectProvider``  (``AUXIN_PRIVACY=direct``) — public SOL transfer via
    the Auxin Anchor program; preserves the original bridge behaviour exactly.

Planned (not yet implemented)
------------------------------
``CloakProvider``    (``AUXIN_PRIVACY=cloak``)    — Colosseum Cloak side-track
``MagicBlockProvider`` (``AUXIN_PRIVACY=magicblock``) — MagicBlock side-track
``UmbraProvider``    (``AUXIN_PRIVACY=umbra``)    — Umbra side-track
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from auxin_sdk.wallet import HardwareWallet


class PaymentResult(BaseModel):
    """Returned by every PrivacyProvider.send_payment() call.

    Fields
    ------
    tx_signature        Confirmed Solana transaction signature, or ``None`` if
                        the call was skipped (idempotent duplicate).
    privacy_provider    Name of the provider that executed the payment
                        (e.g. ``"direct"``).  Used for dashboard display and
                        on-chain bookkeeping.
    is_private          ``True`` when the payment is routed through a privacy
                        protocol that hides the link between payer and payee.
                        ``False`` for the ``direct`` provider.
    confirmation_slot   Solana slot at which the transaction was confirmed, or
                        ``None`` if not available / not applicable.
    metadata            Arbitrary provider-specific fields (e.g. proof hash,
                        relayer address, attempt number).
    """

    tx_signature: str | None
    privacy_provider: str
    is_private: bool
    confirmation_slot: int | None
    metadata: dict


class PrivacyProvider(ABC):
    """Abstract base class for Auxin M2M payment providers.

    All concrete implementations must satisfy the following contract:
      * Thread-safe for concurrent ``send_payment`` calls from the same
        ``Bridge._payment_worker`` coroutine (single-writer; no locks needed).
      * Idempotent on repeated calls with the same ``idempotency_key``.
      * Raise on unrecoverable errors (the worker will log and swallow them).

    Compliance payments are intentionally excluded from this interface —
    they are always direct public-chain calls via ``AuxinProgramClient``.
    """

    @abstractmethod
    async def send_payment(
        self,
        wallet: HardwareWallet,
        owner_pubkey: Any,
        provider_pubkey: Any,
        lamports: int,
        *,
        idempotency_key: str,
    ) -> PaymentResult:
        """Submit a streaming compute payment.

        Parameters
        ----------
        wallet:
            Hardware wallet that signs the transaction.
        owner_pubkey:
            On-chain owner / agent authority public key.
        provider_pubkey:
            Destination provider public key (whitelisted in the agent PDA).
        lamports:
            Amount to transfer (1 SOL = 1 000 000 000 lamports).
        idempotency_key:
            Unique per-payment key.  Repeated calls with the same key must
            return a result with ``tx_signature=None`` instead of
            double-submitting.
        """
        ...

"""Tests for the PrivacyProvider abstraction and DirectProvider.

Coverage
--------
1. DirectProvider.send_payment() delegates to program_client.stream_payment()
   with the same arguments and returns a correctly-shaped PaymentResult.
2. DirectProvider.send_payment() is idempotent — a second call with the same
   idempotency_key returns tx_signature=None without calling stream_payment again.
3. DirectProvider produces is_private=False and privacy_provider="direct".
4. Compliance events in Bridge._compliance_worker bypass the privacy provider —
   they call _submission.log_compliance() directly.  The privacy_provider is
   never touched for compliance events.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.keypair import Keypair

from auxin_sdk.bridge import (
    COMPLIANCE_SEVERITY_ANOMALY,
    Bridge,
    WebsocketBroadcaster,
    _ComplianceTask,
    _PaymentTask,
)
from auxin_sdk.hashing import sha256_hex
from auxin_sdk.oracle import OracleDecision, SafetyOracle
from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider
from auxin_sdk.privacy.direct import DirectProvider
from auxin_sdk.program.client import AuxinProgramClient
from auxin_sdk.schema import TelemetryFrame
from auxin_sdk.sources.mock import MockSource
from auxin_sdk.wallet import HardwareWallet


# ── Helpers ───────────────────────────────────────────────────────────────────


def _anomaly_frame() -> TelemetryFrame:
    torques = [5.0] * 6
    torques[0] = 95.0
    return TelemetryFrame(
        timestamp=datetime.now(UTC),
        joint_positions=[0.1] * 6,
        joint_velocities=[0.0] * 6,
        joint_torques=torques,
        end_effector_pose={"x": 0.0, "y": 0.0, "z": 0.0},
        anomaly_flags=["torque_spike"],
    )


def _mock_program_client(sig: str = "FakePaymentSig222") -> AuxinProgramClient:
    client = MagicMock(spec=AuxinProgramClient)
    client.stream_payment = AsyncMock(return_value=sig)
    client.log_compliance = AsyncMock(return_value="FakeComplianceSig111")
    return client


def _mock_broadcaster() -> WebsocketBroadcaster:
    bc = MagicMock(spec=WebsocketBroadcaster)
    bc.broadcast = AsyncMock()
    bc.start = AsyncMock()
    bc.stop = AsyncMock()
    bc.client_count = 0
    return bc


def _mock_oracle(approved: bool = True) -> SafetyOracle:
    oracle = MagicMock(spec=SafetyOracle)
    oracle.check = AsyncMock(
        return_value=OracleDecision(
            action_approved=approved,
            reason="all clear" if approved else "obstacle",
            confidence=0.95,
            latency_ms=10.0,
            prompt_version="v1",
            used_fallback=False,
        )
    )
    return oracle


# ── DirectProvider unit tests ─────────────────────────────────────────────────


class TestDirectProvider:
    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    @pytest.fixture()
    def provider_pubkey(self) -> object:
        return Keypair().pubkey()

    @pytest.fixture()
    def owner_pubkey(self) -> object:
        return Keypair().pubkey()

    async def test_send_payment_calls_stream_payment(self, wallet, owner_pubkey, provider_pubkey):
        """DirectProvider must delegate to AuxinProgramClient.stream_payment()."""
        client = _mock_program_client("SomeRealSig123")
        provider = DirectProvider(client)

        result = await provider.send_payment(
            wallet=wallet,
            owner_pubkey=owner_pubkey,
            provider_pubkey=provider_pubkey,
            lamports=5_000,
            idempotency_key="key-001",
        )

        client.stream_payment.assert_called_once_with(
            hw_wallet=wallet,
            owner_pubkey=owner_pubkey,
            provider_pubkey=provider_pubkey,
            amount_lamports=5_000,
        )
        assert result.tx_signature == "SomeRealSig123"

    async def test_send_payment_returns_correct_shape(self, wallet, owner_pubkey, provider_pubkey):
        """PaymentResult fields must reflect the direct provider identity."""
        provider = DirectProvider(_mock_program_client())

        result = await provider.send_payment(
            wallet=wallet,
            owner_pubkey=owner_pubkey,
            provider_pubkey=provider_pubkey,
            lamports=5_000,
            idempotency_key="key-002",
        )

        assert isinstance(result, PaymentResult)
        assert result.privacy_provider == "direct"
        assert result.is_private is False
        assert result.tx_signature == "FakePaymentSig222"

    async def test_send_payment_idempotent_on_duplicate_key(
        self, wallet, owner_pubkey, provider_pubkey
    ):
        """Second call with the same idempotency_key must return None sig, no RPC call."""
        client = _mock_program_client()
        provider = DirectProvider(client)

        key = "key-dupe"
        await provider.send_payment(
            wallet=wallet,
            owner_pubkey=owner_pubkey,
            provider_pubkey=provider_pubkey,
            lamports=5_000,
            idempotency_key=key,
        )
        # Second call — same key
        result2 = await provider.send_payment(
            wallet=wallet,
            owner_pubkey=owner_pubkey,
            provider_pubkey=provider_pubkey,
            lamports=5_000,
            idempotency_key=key,
        )

        # stream_payment must only have been called once
        assert client.stream_payment.call_count == 1
        assert result2.tx_signature is None
        assert result2.privacy_provider == "direct"
        assert result2.is_private is False

    async def test_different_keys_are_not_deduplicated(self, wallet, owner_pubkey, provider_pubkey):
        """Different idempotency_keys must each call stream_payment independently."""
        client = _mock_program_client()
        provider = DirectProvider(client)

        for i in range(3):
            await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key=f"key-{i}",
            )

        assert client.stream_payment.call_count == 3

    async def test_exception_propagates(self, wallet, owner_pubkey, provider_pubkey):
        """Non-retriable errors must propagate out of send_payment."""
        client = MagicMock(spec=AuxinProgramClient)
        client.stream_payment = AsyncMock(side_effect=RuntimeError("program error"))
        provider = DirectProvider(client)

        with pytest.raises(RuntimeError, match="program error"):
            await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="key-err",
            )


# ── Compliance bypass tests ───────────────────────────────────────────────────


class TestComplianceBypassesPrivacyProvider:
    """
    Architecture rule: compliance events MUST NEVER be routed through the
    PrivacyProvider.  They go direct to the public chain via log_compliance().
    """

    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    def _make_bridge_with_spy_provider(
        self,
        program_client: AuxinProgramClient,
        wallet: HardwareWallet,
    ) -> tuple[Bridge, MagicMock]:
        """Return a bridge and a spy PrivacyProvider."""
        spy = MagicMock(spec=PrivacyProvider)
        spy.send_payment = AsyncMock(
            return_value=PaymentResult(
                tx_signature="SpySig",
                privacy_provider="spy",
                is_private=False,
                confirmation_slot=None,
                metadata={},
            )
        )
        bridge = Bridge(
            source=MockSource(rate_hz=0),
            oracle=_mock_oracle(),
            program_client=program_client,
            wallet=wallet,
            ws_broadcaster=_mock_broadcaster(),
            privacy_provider=spy,
            owner_pubkey=wallet.pubkey,
            provider_pubkey=Keypair().pubkey(),
            healthz_port=0,
        )
        return bridge, spy

    async def test_compliance_worker_never_calls_privacy_provider(self, wallet):
        """_compliance_worker calls log_compliance, never privacy_provider.send_payment."""
        program_client = _mock_program_client()
        bridge, spy = self._make_bridge_with_spy_provider(program_client, wallet)

        frame = _anomaly_frame()
        task = _ComplianceTask(
            frame=frame,
            telemetry_hash=sha256_hex(frame),
            severity=COMPLIANCE_SEVERITY_ANOMALY,
            reason_code=0x0001,
        )
        await bridge._compliance_queue.put(task)

        worker = asyncio.create_task(bridge._compliance_worker())
        await asyncio.sleep(0.05)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

        # Compliance must go to program_client, not the privacy provider
        program_client.log_compliance.assert_called_once()
        spy.send_payment.assert_not_called()

    async def test_process_anomaly_frame_never_touches_privacy_provider(self, wallet):
        """process() with an anomaly frame must not call privacy_provider.send_payment."""
        program_client = _mock_program_client()
        bridge, spy = self._make_bridge_with_spy_provider(program_client, wallet)

        await bridge.process(_anomaly_frame())

        spy.send_payment.assert_not_called()
        assert bridge._compliance_queue.qsize() == 1
        assert bridge._payment_queue.qsize() == 0

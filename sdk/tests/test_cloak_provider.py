"""Tests for the CloakProvider privacy integration.

Coverage
--------
1. CloakProvider.send_payment() returns PaymentResult with is_private=True,
   privacy_provider="cloak" when the subprocess succeeds.
2. Each payment produces a unique UTXO commitment (stealth address equivalent).
3. On subprocess failure, CloakProvider falls back to DirectProvider.
4. On subprocess failure WITHOUT fallback, the error propagates.
5. Idempotency: duplicate idempotency_key skips the subprocess.
6. Compliance events are never routed through CloakProvider.
7. Node.js not found raises a clear RuntimeError.
8. Subprocess timeout produces a clear error.
"""

from __future__ import annotations

import asyncio
import json
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
)
from auxin_sdk.hashing import sha256_hex
from auxin_sdk.oracle import OracleDecision, SafetyOracle
from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider
from auxin_sdk.privacy.cloak import CloakProvider
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


def _mock_program_client() -> AuxinProgramClient:
    client = MagicMock(spec=AuxinProgramClient)
    client.stream_payment = AsyncMock(return_value="FakeDirectSig")
    client.log_compliance = AsyncMock(return_value="FakeComplianceSig")
    return client


def _mock_broadcaster() -> WebsocketBroadcaster:
    bc = MagicMock(spec=WebsocketBroadcaster)
    bc.broadcast = AsyncMock()
    bc.start = AsyncMock()
    bc.stop = AsyncMock()
    bc.client_count = 0
    return bc


def _mock_oracle() -> SafetyOracle:
    oracle = MagicMock(spec=SafetyOracle)
    oracle.check = AsyncMock(
        return_value=OracleDecision(
            action_approved=True,
            reason="ok",
            confidence=0.95,
            latency_ms=10.0,
            prompt_version="v1",
            used_fallback=False,
        )
    )
    return oracle


def _make_subprocess_result(
    signature: str = "CloakSig123abc",
    utxo_commitment: str = "deadbeef",
    utxo_private_key_hex: str = "cafe0001",
    confirmation_slot: int = 999,
) -> bytes:
    """Build the JSON bytes that a successful deposit.mjs would write to stdout."""
    return (
        json.dumps(
            {
                "signature": signature,
                "utxo_commitment": utxo_commitment,
                "utxo_private_key_hex": utxo_private_key_hex,
                "confirmation_slot": confirmation_slot,
            }
        )
        + "\n"
    ).encode()


# ── Subprocess mock helper ────────────────────────────────────────────────────


def _mock_subprocess(
    stdout: bytes = _make_subprocess_result(),
    stderr: bytes = b"",
    returncode: int = 0,
):
    """Patch asyncio.create_subprocess_exec to return a fake process."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return patch(
        "auxin_sdk.privacy.cloak.asyncio.create_subprocess_exec",
        return_value=proc,
    )


# ── CloakProvider unit tests ─────────────────────────────────────────────────


class TestCloakProvider:
    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    @pytest.fixture()
    def provider(self) -> CloakProvider:
        return CloakProvider("https://api.devnet.solana.com")

    @pytest.fixture()
    def provider_with_fallback(self) -> CloakProvider:
        fallback = DirectProvider(_mock_program_client())
        return CloakProvider("https://api.devnet.solana.com", fallback=fallback)

    @pytest.fixture()
    def provider_pubkey(self) -> object:
        return Keypair().pubkey()

    @pytest.fixture()
    def owner_pubkey(self) -> object:
        return Keypair().pubkey()

    async def test_send_payment_returns_private_result(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Successful Cloak deposit returns is_private=True, privacy_provider='cloak'."""
        with _mock_subprocess():
            result = await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="key-001",
            )

        assert isinstance(result, PaymentResult)
        assert result.is_private is True
        assert result.privacy_provider == "cloak"
        assert result.tx_signature == "CloakSig123abc"
        assert result.confirmation_slot == 999
        assert "utxo_commitment" in result.metadata
        assert result.metadata["utxo_commitment"] == "deadbeef"

    async def test_unique_utxo_per_payment(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Each payment should produce a distinct UTXO commitment."""
        results = []
        for i in range(3):
            stdout = _make_subprocess_result(
                signature=f"Sig{i}",
                utxo_commitment=f"commit_{i:04d}",
                utxo_private_key_hex=f"pk_{i:04d}",
            )
            with _mock_subprocess(stdout=stdout):
                r = await provider.send_payment(
                    wallet=wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    lamports=5_000,
                    idempotency_key=f"key-{i}",
                )
                results.append(r)

        commitments = [r.metadata["utxo_commitment"] for r in results]
        assert len(set(commitments)) == 3, "Each payment must produce a unique UTXO commitment"

    async def test_idempotent_skip(self, provider, wallet, owner_pubkey, provider_pubkey):
        """Duplicate idempotency_key skips the subprocess entirely."""
        with _mock_subprocess() as mock_exec:
            await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="dupe-key",
            )
            result2 = await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="dupe-key",
            )

        assert result2.tx_signature is None
        assert result2.is_private is True
        # Subprocess should only be called once (the second call is skipped)
        assert mock_exec.call_count == 1

    async def test_fallback_to_direct_on_subprocess_error(
        self, provider_with_fallback, wallet, owner_pubkey, provider_pubkey
    ):
        """When Cloak subprocess fails, fallback to DirectProvider."""
        stderr = json.dumps({"error": "relayer unreachable"}).encode()
        with _mock_subprocess(stdout=b"", stderr=stderr, returncode=1):
            result = await provider_with_fallback.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="fallback-key",
            )

        # Should have fallen back to DirectProvider
        assert result.privacy_provider == "direct"
        assert result.is_private is False
        assert result.tx_signature == "FakeDirectSig"

    async def test_error_propagates_without_fallback(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Without fallback, subprocess errors raise RuntimeError."""
        stderr = json.dumps({"error": "boom"}).encode()
        with _mock_subprocess(stdout=b"", stderr=stderr, returncode=1):
            with pytest.raises(RuntimeError, match="Cloak deposit failed: boom"):
                await provider.send_payment(
                    wallet=wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    lamports=5_000,
                    idempotency_key="err-key",
                )

    async def test_node_not_found_raises_clear_error(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Missing Node.js raises a helpful RuntimeError."""
        with patch(
            "auxin_sdk.privacy.cloak.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("node"),
        ):
            with pytest.raises(RuntimeError, match="Node.js not found"):
                await provider.send_payment(
                    wallet=wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    lamports=5_000,
                    idempotency_key="nonode-key",
                )

    async def test_subprocess_timeout_raises_clear_error(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Subprocess timeout produces an actionable error message."""

        async def _slow_communicate(*args, **kwargs):
            await asyncio.sleep(999)

        proc = AsyncMock()
        proc.communicate = _slow_communicate

        with patch(
            "auxin_sdk.privacy.cloak.asyncio.create_subprocess_exec",
            return_value=proc,
        ), patch(
            "auxin_sdk.privacy.cloak._SUBPROCESS_TIMEOUT_S", 0.01
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await provider.send_payment(
                    wallet=wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    lamports=5_000,
                    idempotency_key="timeout-key",
                )


# ── Compliance bypass tests ───────────────────────────────────────────────────


class TestComplianceBypassesCloakProvider:
    """
    Architecture rule: compliance events MUST NEVER be routed through the
    CloakProvider.  They always go to the public chain via log_compliance().
    """

    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    async def test_compliance_worker_never_calls_cloak(self, wallet):
        """_compliance_worker calls log_compliance, never the CloakProvider."""
        program_client = _mock_program_client()
        cloak = CloakProvider("https://api.devnet.solana.com")
        # Spy on the provider — it should never be called for compliance
        cloak.send_payment = AsyncMock()  # type: ignore[assignment]

        bridge = Bridge(
            source=MockSource(rate_hz=0),
            oracle=_mock_oracle(),
            program_client=program_client,
            wallet=wallet,
            ws_broadcaster=_mock_broadcaster(),
            privacy_provider=cloak,
            owner_pubkey=wallet.pubkey,
            provider_pubkey=Keypair().pubkey(),
            healthz_port=0,
        )

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

        # Compliance went through program_client directly
        program_client.log_compliance.assert_called_once()
        # CloakProvider was NOT touched
        cloak.send_payment.assert_not_called()

"""Tests for UmbraProvider.

Coverage
--------
1. send_payment() returns PaymentResult with is_private=True, privacy_provider="umbra".
2. Result metadata includes utxo_commitment, provider_pubkey, mint.
3. Idempotency: duplicate idempotency_key skips the sidecar call.
4. Fallback to DirectProvider when the sidecar returns HTTP 500.
5. Fallback to DirectProvider when the sidecar is unreachable.
6. Error propagates when no fallback is configured.
7. health_check() returns True on 200, False on network error.
8. export_viewing_key() calls the sidecar and returns key + scope.
9. Compliance events are never routed through UmbraProvider.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
from auxin_sdk.privacy.base import PaymentResult
from auxin_sdk.privacy.direct import DirectProvider
from auxin_sdk.privacy.umbra import UmbraProvider
from auxin_sdk.program.client import AuxinProgramClient
from auxin_sdk.schema import TelemetryFrame
from auxin_sdk.sources.mock import MockSource
from auxin_sdk.wallet import HardwareWallet


# ── Helpers ───────────────────────────────────────────────────────────────────


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


def _mock_httpx_post(response_data: dict, status_code: int = 200):
    """Patch httpx.AsyncClient to return a fake sidecar response for POST."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json = MagicMock(return_value=response_data)
    mock_resp.text = json.dumps(response_data)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock(return_value=mock_resp)

    return patch("auxin_sdk.privacy.umbra.httpx.AsyncClient", return_value=mock_client)


# ── Unit tests ────────────────────────────────────────────────────────────────


class TestUmbraProvider:
    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    @pytest.fixture()
    def provider(self) -> UmbraProvider:
        return UmbraProvider("http://localhost:3002")

    @pytest.fixture()
    def provider_with_fallback(self) -> UmbraProvider:
        fallback = DirectProvider(_mock_program_client())
        return UmbraProvider("http://localhost:3002", fallback=fallback)

    @pytest.fixture()
    def owner_pubkey(self) -> object:
        return Keypair().pubkey()

    @pytest.fixture()
    def provider_pubkey(self) -> object:
        return Keypair().pubkey()

    async def test_send_payment_returns_private_result(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Successful deposit returns is_private=True, privacy_provider='umbra'."""
        sidecar_resp = {
            "signature": "UmbraSig123abc",
            "utxo_commitment": "deadbeef1234",
        }
        with _mock_httpx_post(sidecar_resp):
            result = await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="key-001",
            )

        assert isinstance(result, PaymentResult)
        assert result.is_private is True
        assert result.privacy_provider == "umbra"
        assert result.tx_signature == "UmbraSig123abc"

    async def test_result_metadata_shape(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Result metadata includes utxo_commitment, provider_pubkey, mint."""
        sidecar_resp = {
            "signature": "UmbraSig456",
            "utxo_commitment": "abcd1234",
        }
        with _mock_httpx_post(sidecar_resp):
            result = await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="key-meta",
            )

        assert result.metadata["utxo_commitment"] == "abcd1234"
        assert "provider_pubkey" in result.metadata
        assert "mint" in result.metadata

    async def test_idempotent_skip(self, provider, wallet, owner_pubkey, provider_pubkey):
        """Duplicate idempotency_key skips the sidecar call."""
        sidecar_resp = {"signature": "Sig1", "utxo_commitment": "c1"}
        with _mock_httpx_post(sidecar_resp) as mock_http:
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
        assert result2.metadata.get("skipped") == "duplicate"
        # POST should only be called once
        mock_http.return_value.post.assert_called_once()

    async def test_fallback_on_sidecar_error(
        self, provider_with_fallback, wallet, owner_pubkey, provider_pubkey
    ):
        """HTTP 500 from the sidecar triggers fallback to DirectProvider."""
        with _mock_httpx_post({"error": "ZK prover failed"}, status_code=500):
            result = await provider_with_fallback.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="fail-key",
            )

        assert result.privacy_provider == "direct"
        assert result.is_private is False
        assert result.tx_signature == "FakeDirectSig"

    async def test_fallback_on_network_error(
        self, provider_with_fallback, wallet, owner_pubkey, provider_pubkey
    ):
        """Network error triggers fallback to DirectProvider."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with patch("auxin_sdk.privacy.umbra.httpx.AsyncClient", return_value=mock_client):
            result = await provider_with_fallback.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="net-fail-key",
            )

        assert result.privacy_provider == "direct"
        assert result.tx_signature == "FakeDirectSig"

    async def test_error_propagates_without_fallback(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Without fallback, sidecar errors raise RuntimeError."""
        with _mock_httpx_post({"error": "boom"}, status_code=500):
            with pytest.raises(RuntimeError, match="Umbra sidecar error 500"):
                await provider.send_payment(
                    wallet=wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    lamports=5_000,
                    idempotency_key="err-key",
                )

    async def test_health_check_true_on_200(self, provider):
        """health_check() returns True when sidecar responds 200."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("auxin_sdk.privacy.umbra.httpx.AsyncClient", return_value=mock_client):
            assert await provider.health_check() is True

    async def test_health_check_false_on_error(self, provider):
        """health_check() returns False when sidecar is unreachable."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with patch("auxin_sdk.privacy.umbra.httpx.AsyncClient", return_value=mock_client):
            assert await provider.health_check() is False

    async def test_export_viewing_key(self, provider, wallet):
        """export_viewing_key() calls the sidecar and returns key + scope."""
        sidecar_resp = {
            "viewing_key": "abcdef1234567890",
            "scope": "yearly",
        }
        with _mock_httpx_post(sidecar_resp):
            result = await provider.export_viewing_key(
                wallet, scope="yearly", year=2026
            )

        assert result["viewing_key"] == "abcdef1234567890"
        assert result["scope"] == "yearly"


# ── Compliance bypass tests ───────────────────────────────────────────────────


class TestComplianceBypassesUmbraProvider:
    """
    Architecture rule: compliance events MUST NEVER be routed through
    UmbraProvider.  They always go to the public chain via log_compliance().
    """

    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    async def test_compliance_worker_never_calls_umbra(self, wallet):
        """_compliance_worker calls log_compliance, never the UmbraProvider."""
        program_client = _mock_program_client()
        umbra = UmbraProvider("http://localhost:3002")
        umbra.send_payment = AsyncMock()  # type: ignore[assignment]

        bridge = Bridge(
            source=MockSource(rate_hz=0),
            oracle=_mock_oracle(),
            program_client=program_client,
            wallet=wallet,
            ws_broadcaster=_mock_broadcaster(),
            privacy_provider=umbra,
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

        program_client.log_compliance.assert_called_once()
        umbra.send_payment.assert_not_called()

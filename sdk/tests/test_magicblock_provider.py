"""Tests for MagicBlockProvider.

Coverage
--------
1. send_payment() returns PaymentResult with is_private=True, privacy_provider="magicblock".
2. Successful response shape — signature propagated from API.
3. Idempotency: duplicate idempotency_key skips the API call.
4. Fallback to DirectProvider when the API returns HTTP 400.
5. Fallback to DirectProvider when the API is unreachable.
6. Error propagates when no fallback is configured.
7. AML rejection (HTTP 400) raises RuntimeError without fallback.
8. delegate_budget() calls POST /v1/spl/deposit and returns a signature.
9. Compliance events are never routed through MagicBlockProvider.
"""

from __future__ import annotations

import asyncio
import base64
import json
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
from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider
from auxin_sdk.privacy.direct import DirectProvider
from auxin_sdk.privacy.magicblock import MagicBlockProvider, _sign_transaction_bytes
from auxin_sdk.program.client import AuxinProgramClient
from auxin_sdk.schema import TelemetryFrame
from datetime import UTC, datetime
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


def _make_api_response(
    tx_b64: str = base64.b64encode(b"\x00" * 64).decode(),
    send_to: str = "https://api.devnet.solana.com",
) -> dict:
    """Build a fake MagicBlock API response (deposit or transfer)."""
    return {
        "kind": "transfer",
        "transactionBase64": tx_b64,
        "sendTo": send_to,
        "recentBlockhash": "EkCkB6jq4w5K6u9bHFVmHReEe8k8Tg9hXzLUX2Py3B1",
        "lastValidBlockHeight": 1000,
        "instructionCount": 2,
        "requiredSigners": ["owner_pubkey_placeholder"],
    }


def _mock_httpx_post(response_data: dict, status_code: int = 200):
    """Patch httpx.AsyncClient.post to return a fake API response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json = MagicMock(return_value=response_data)
    mock_resp.text = json.dumps(response_data)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    return patch("auxin_sdk.privacy.magicblock.httpx.AsyncClient", return_value=mock_client)


def _mock_solana_send(signature: str = "MagicBlockSig123", slot: int = 42):
    """Patch AsyncClient.send_raw_transaction to return a fake signature."""
    mock_resp = MagicMock()
    mock_resp.value = signature

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.send_raw_transaction = AsyncMock(return_value=mock_resp)

    return patch("auxin_sdk.privacy.magicblock.AsyncClient", return_value=mock_client)


# ── Unit tests ────────────────────────────────────────────────────────────────


class TestMagicBlockProvider:
    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    @pytest.fixture()
    def provider(self) -> MagicBlockProvider:
        return MagicBlockProvider("https://api.devnet.solana.com")

    @pytest.fixture()
    def provider_with_fallback(self) -> MagicBlockProvider:
        fallback = DirectProvider(_mock_program_client())
        return MagicBlockProvider(
            "https://api.devnet.solana.com",
            fallback=fallback,
        )

    @pytest.fixture()
    def owner_pubkey(self) -> object:
        return Keypair().pubkey()

    @pytest.fixture()
    def provider_pubkey(self) -> object:
        return Keypair().pubkey()

    async def test_send_payment_returns_private_result(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Successful call returns is_private=True, privacy_provider='magicblock'."""
        with (
            _mock_httpx_post(_make_api_response()),
            _mock_solana_send("MagicBlockSig123"),
            patch("auxin_sdk.privacy.magicblock._sign_transaction_bytes", return_value=b"\x00" * 64),
        ):
            result = await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="key-001",
            )

        assert isinstance(result, PaymentResult)
        assert result.is_private is True
        assert result.privacy_provider == "magicblock"
        assert result.tx_signature == "MagicBlockSig123"

    async def test_result_metadata_shape(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Result metadata includes provider_pubkey, mint, cluster."""
        with (
            _mock_httpx_post(_make_api_response()),
            _mock_solana_send(),
            patch("auxin_sdk.privacy.magicblock._sign_transaction_bytes", return_value=b"\x00" * 64),
        ):
            result = await provider.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="key-meta",
            )

        assert "provider_pubkey" in result.metadata
        assert "mint" in result.metadata
        assert "cluster" in result.metadata
        assert result.metadata["cluster"] == "devnet"

    async def test_idempotent_skip(self, provider, wallet, owner_pubkey, provider_pubkey):
        """Duplicate idempotency_key skips the API call."""
        with (
            _mock_httpx_post(_make_api_response()) as mock_http,
            _mock_solana_send(),
            patch("auxin_sdk.privacy.magicblock._sign_transaction_bytes", return_value=b"\x00" * 64),
        ):
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

        # Second call returns None signature (skipped)
        assert result2.tx_signature is None
        assert result2.is_private is True
        assert result2.metadata.get("skipped") == "duplicate"
        # API should only be called once
        mock_http.return_value.post.assert_called_once()

    async def test_fallback_on_api_http_error(
        self, provider_with_fallback, wallet, owner_pubkey, provider_pubkey
    ):
        """HTTP 400 from MagicBlock API triggers fallback to DirectProvider."""
        with _mock_httpx_post({"detail": "AML check failed"}, status_code=400):
            result = await provider_with_fallback.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="aml-fail-key",
            )

        assert result.privacy_provider == "direct"
        assert result.is_private is False
        assert result.tx_signature == "FakeDirectSig"

    async def test_fallback_on_network_error(
        self, provider_with_fallback, wallet, owner_pubkey, provider_pubkey
    ):
        """Network error from MagicBlock API triggers fallback to DirectProvider."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with patch("auxin_sdk.privacy.magicblock.httpx.AsyncClient", return_value=mock_client):
            result = await provider_with_fallback.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="network-fail-key",
            )

        assert result.privacy_provider == "direct"
        assert result.tx_signature == "FakeDirectSig"

    async def test_error_propagates_without_fallback(
        self, provider, wallet, owner_pubkey, provider_pubkey
    ):
        """Without fallback, API errors raise RuntimeError."""
        with _mock_httpx_post({"detail": "AML check failed"}, status_code=400):
            with pytest.raises(RuntimeError, match="MagicBlock API error 400"):
                await provider.send_payment(
                    wallet=wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    lamports=5_000,
                    idempotency_key="err-key",
                )

    async def test_delegate_budget_calls_deposit(self, provider, wallet):
        """delegate_budget() calls POST /v1/spl/deposit and returns a signature."""
        with (
            _mock_httpx_post(_make_api_response()) as mock_http,
            _mock_solana_send("DepositSig456"),
            patch("auxin_sdk.privacy.magicblock._sign_transaction_bytes", return_value=b"\x00" * 64),
        ):
            sig = await provider.delegate_budget(wallet, lamports=100_000_000)

        assert sig == "DepositSig456"
        # Verify /v1/spl/deposit was called
        call_args = mock_http.return_value.post.call_args
        assert "/v1/spl/deposit" in call_args[0][0]

    async def test_api_key_sent_as_bearer(self, wallet, owner_pubkey, provider_pubkey):
        """API key is forwarded as Authorization: Bearer header."""
        provider_with_key = MagicBlockProvider(
            "https://api.devnet.solana.com",
            api_key="test-api-key-xyz",
        )

        captured_headers: dict = {}

        async def _fake_post(url, *, json=None, headers=None):
            captured_headers.update(headers or {})
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json = MagicMock(return_value=_make_api_response())
            return mock_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_fake_post)

        with (
            patch("auxin_sdk.privacy.magicblock.httpx.AsyncClient", return_value=mock_client),
            _mock_solana_send(),
            patch("auxin_sdk.privacy.magicblock._sign_transaction_bytes", return_value=b"\x00" * 64),
        ):
            await provider_with_key.send_payment(
                wallet=wallet,
                owner_pubkey=owner_pubkey,
                provider_pubkey=provider_pubkey,
                lamports=5_000,
                idempotency_key="key-auth",
            )

        assert captured_headers.get("Authorization") == "Bearer test-api-key-xyz"


# ── Compliance bypass tests ───────────────────────────────────────────────────


class TestComplianceBypassesMagicBlockProvider:
    """
    Architecture rule: compliance events MUST NEVER be routed through
    MagicBlockProvider.  They always go to the public chain via log_compliance().
    """

    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    async def test_compliance_worker_never_calls_magicblock(self, wallet):
        """_compliance_worker calls log_compliance, never the MagicBlockProvider."""
        program_client = _mock_program_client()
        mb_provider = MagicBlockProvider("https://api.devnet.solana.com")
        mb_provider.send_payment = AsyncMock()  # type: ignore[assignment]

        bridge = Bridge(
            source=MockSource(rate_hz=0),
            oracle=_mock_oracle(),
            program_client=program_client,
            wallet=wallet,
            ws_broadcaster=_mock_broadcaster(),
            privacy_provider=mb_provider,
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
        # MagicBlockProvider was NOT touched
        mb_provider.send_payment.assert_not_called()

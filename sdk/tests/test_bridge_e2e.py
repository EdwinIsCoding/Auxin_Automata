"""
Bridge integration tests.

File is split into two sections:

1. TestBridgeUnit  — fast in-process tests; no network, no real oracle, no aiohttp
   servers started.  Always runs in CI.

2. TestBridgeDevnet — Solana Devnet end-to-end.  Skipped unless DEVNET_KEYPAIR
   is set.  Asserts a ComplianceEvent tx signature appears on-chain within 5 s
   after an injected anomaly.

   Required env vars to run the Devnet suite:
     DEVNET_KEYPAIR      Path to a funded Devnet keypair (JSON byte array)
     HELIUS_RPC_URL      Helius/QuickNode Devnet RPC (falls back to public devnet)
     AUXIN_PROGRAM_ID    Optional — resolved from /programs/deployed.json otherwise
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from solders.keypair import Keypair

from auxin_sdk.bridge import (
    COMPLIANCE_SEVERITY_ANOMALY,
    PAYMENT_QUEUE_MAXSIZE,
    Bridge,
    WebsocketBroadcaster,
    _ComplianceTask,
    _PaymentTask,
)
from auxin_sdk.hashing import sha256_hex
from auxin_sdk.oracle import OracleDecision, SafetyOracle
from auxin_sdk.privacy.direct import DirectProvider
from auxin_sdk.program.client import AuxinProgramClient
from auxin_sdk.schema import TelemetryFrame
from auxin_sdk.sources.mock import MockSource
from auxin_sdk.wallet import HardwareWallet

# ── Shared helpers ────────────────────────────────────────────────────────────


def _normal_frame() -> TelemetryFrame:
    return TelemetryFrame(
        timestamp=datetime.now(UTC),
        joint_positions=[0.1] * 6,
        joint_velocities=[0.0] * 6,
        joint_torques=[5.0] * 6,
        end_effector_pose={"x": 0.1, "y": 0.2, "z": 0.3},
        anomaly_flags=[],
    )


def _anomaly_frame() -> TelemetryFrame:
    torques = [5.0] * 6
    torques[0] = 95.0
    return TelemetryFrame(
        timestamp=datetime.now(UTC),
        joint_positions=[0.1] * 6,
        joint_velocities=[0.0] * 6,
        joint_torques=torques,
        end_effector_pose={"x": 0.1, "y": 0.2, "z": 0.3},
        anomaly_flags=["torque_spike"],
    )


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
            reason="all clear" if approved else "obstacle detected",
            confidence=0.95,
            latency_ms=10.0,
            prompt_version="safety_oracle_v1",
            used_fallback=False,
        )
    )
    return oracle


def _mock_program_client() -> AuxinProgramClient:
    client = MagicMock(spec=AuxinProgramClient)
    client.log_compliance = AsyncMock(return_value="FakeComplianceSig111")
    client.stream_payment = AsyncMock(return_value="FakePaymentSig222")
    return client


def _make_bridge(
    source: MockSource,
    oracle: SafetyOracle,
    program_client: AuxinProgramClient,
    wallet: HardwareWallet,
    broadcaster: WebsocketBroadcaster,
    provider_pubkey=None,
) -> Bridge:
    return Bridge(
        source=source,
        oracle=oracle,
        program_client=program_client,
        wallet=wallet,
        ws_broadcaster=broadcaster,
        # DirectProvider wraps program_client, so existing mocks on
        # program_client.stream_payment still get called through the provider.
        privacy_provider=DirectProvider(program_client),
        owner_pubkey=wallet.pubkey,
        provider_pubkey=provider_pubkey or Keypair().pubkey(),
        healthz_port=0,  # disable HTTP servers in unit tests
    )


# ── Unit tests ────────────────────────────────────────────────────────────────


class TestBridgeUnit:
    """Fast, in-process tests.  No network, no aiohttp servers."""

    @pytest.fixture()
    def wallet(self, tmp_path: Path) -> HardwareWallet:
        return HardwareWallet.load_or_create(tmp_path / "hw.json")

    # ── process() routing ─────────────────────────────────────────────────────

    async def test_anomaly_frame_enqueues_compliance_task(self, wallet):
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )

        await bridge.process(_anomaly_frame())

        assert bridge._compliance_queue.qsize() == 1
        assert bridge._payment_queue.qsize() == 0

    async def test_anomaly_frame_never_goes_to_payment_queue(self, wallet):
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )
        await bridge.process(_anomaly_frame())
        assert bridge._payment_queue.qsize() == 0

    async def test_normal_frame_enqueues_payment_task(self, wallet):
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )
        await bridge.process(_normal_frame())

        assert bridge._payment_queue.qsize() == 1
        assert bridge._compliance_queue.qsize() == 0

    async def test_oracle_not_called_from_process(self, wallet):
        """Oracle is called by the payment_worker, not by process() itself."""
        oracle = _mock_oracle()
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            oracle,
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )
        await bridge.process(_normal_frame())
        oracle.check.assert_not_called()

    async def test_broadcaster_receives_raw_telemetry(self, wallet):
        broadcaster = _mock_broadcaster()
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            broadcaster,
        )
        frame = _normal_frame()
        await bridge.process(frame)
        broadcaster.broadcast.assert_called_once()
        call_args = broadcaster.broadcast.call_args[0][0]
        assert call_args["type"] == "telemetry"

    # ── Backpressure ──────────────────────────────────────────────────────────

    async def test_backpressure_drops_normal_frame_when_payment_queue_full(self, wallet):
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )

        # Fill the payment queue to capacity
        dummy_frame = _normal_frame()
        for _ in range(PAYMENT_QUEUE_MAXSIZE):
            bridge._payment_queue.put_nowait(_PaymentTask(frame=dummy_frame))

        assert bridge._payment_queue.full()

        dropped_before = bridge._frames_dropped
        await bridge.process(_normal_frame())
        assert bridge._frames_dropped == dropped_before + 1
        # Queue depth must not have grown
        assert bridge._payment_queue.qsize() == PAYMENT_QUEUE_MAXSIZE

    async def test_compliance_never_dropped_even_when_payment_queue_full(self, wallet):
        """
        ARCHITECTURE RULE: compliance events bypass the payment queue entirely.
        An anomaly frame must land in the compliance queue even when payment queue
        is at capacity.
        """
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )

        # Saturate the payment queue
        dummy_frame = _normal_frame()
        for _ in range(PAYMENT_QUEUE_MAXSIZE):
            bridge._payment_queue.put_nowait(_PaymentTask(frame=dummy_frame))

        dropped_before = bridge._frames_dropped
        await bridge.process(_anomaly_frame())

        assert bridge._compliance_queue.qsize() == 1
        assert bridge._frames_dropped == dropped_before  # NOT incremented

    # ── Compliance hash ───────────────────────────────────────────────────────

    async def test_compliance_task_has_correct_hash(self, wallet):
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )
        frame = _anomaly_frame()
        await bridge.process(frame)

        task: _ComplianceTask = bridge._compliance_queue.get_nowait()
        assert task.telemetry_hash == sha256_hex(frame)
        assert len(task.telemetry_hash) == 64
        assert task.severity == COMPLIANCE_SEVERITY_ANOMALY

    # ── Worker: oracle approval → payment ─────────────────────────────────────

    async def test_payment_worker_calls_stream_payment_on_oracle_approval(self, wallet):
        program_client = _mock_program_client()
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(approved=True),
            program_client,
            wallet,
            _mock_broadcaster(),
            provider_pubkey=Keypair().pubkey(),
        )

        # Directly seed the payment queue and run the worker for one item
        frame = _normal_frame()
        await bridge._payment_queue.put(_PaymentTask(frame=frame))

        worker = asyncio.create_task(bridge._payment_worker())
        await asyncio.sleep(0.05)  # let worker drain one item
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

        program_client.stream_payment.assert_called_once()
        assert bridge._payments_total == 1

    async def test_payment_worker_pushes_compliance_on_oracle_denial(self, wallet):
        program_client = _mock_program_client()
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(approved=False),
            program_client,
            wallet,
            _mock_broadcaster(),
        )

        await bridge._payment_queue.put(_PaymentTask(frame=_normal_frame()))

        worker = asyncio.create_task(bridge._payment_worker())
        await asyncio.sleep(0.05)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

        # Oracle denial must re-route to compliance queue
        assert bridge._compliance_queue.qsize() == 1
        program_client.stream_payment.assert_not_called()

    # ── Worker: compliance worker calls log_compliance ────────────────────────

    async def test_compliance_worker_calls_log_compliance(self, wallet):
        program_client = _mock_program_client()
        broadcaster = _mock_broadcaster()
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            program_client,
            wallet,
            broadcaster,
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
        assert bridge._compliance_total == 1
        # Broadcaster must have received the compliance_event
        calls = [c[0][0] for c in broadcaster.broadcast.call_args_list]
        compliance_calls = [c for c in calls if c.get("type") == "compliance_event"]
        assert len(compliance_calls) == 1
        assert compliance_calls[0]["data"]["severity"] == COMPLIANCE_SEVERITY_ANOMALY

    # ── Health state ──────────────────────────────────────────────────────────

    async def test_healthz_handler_returns_expected_keys(self, wallet):
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )
        request = MagicMock()
        response = await bridge._healthz_handler(request)
        body = response.body
        import json

        data = json.loads(body)
        for key in (
            "source_status",
            "last_successful_tx",
            "last_oracle_latency_ms",
            "queue_depths",
            "uptime_seconds",
            "frames_processed",
        ):
            assert key in data, f"Missing key in /healthz: {key}"

    # ── Frames processed counter ──────────────────────────────────────────────

    async def test_frames_processed_counter_increments(self, wallet):
        bridge = _make_bridge(
            MockSource(rate_hz=0),
            _mock_oracle(),
            _mock_program_client(),
            wallet,
            _mock_broadcaster(),
        )
        for _ in range(5):
            await bridge.process(_normal_frame())
        assert bridge._frames_processed == 5


# ── Devnet E2E test ───────────────────────────────────────────────────────────


def _devnet_keypair_available() -> bool:
    return bool(os.environ.get("DEVNET_KEYPAIR"))


@pytest.mark.network
@pytest.mark.skipif(
    not _devnet_keypair_available(),
    reason="DEVNET_KEYPAIR not set — skipping Devnet E2E (run with -m network)",
)
class TestBridgeDevnet:
    """
    End-to-end test against Solana Devnet.

    Run manually:
        DEVNET_KEYPAIR=~/.config/auxin/hardware.json \\
        HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \\
        pytest -m network tests/test_bridge_e2e.py::TestBridgeDevnet -v
    """

    @pytest.fixture()
    async def funded_wallet(self) -> HardwareWallet:
        keypair_path = os.environ["DEVNET_KEYPAIR"]
        wallet = HardwareWallet.load_or_create(keypair_path)
        rpc_url = os.environ.get("HELIUS_RPC_URL", "https://api.devnet.solana.com")
        balance = await wallet.get_balance(rpc_url)
        if balance < 10_000_000:  # < 0.01 SOL — airdrop if needed
            await wallet.request_airdrop(rpc_url, 1.0)
            await asyncio.sleep(15)
        return wallet

    async def test_anomaly_compliance_event_on_devnet(
        self,
        funded_wallet: HardwareWallet,
        tmp_path: Path,
    ) -> None:
        """
        Spin up Bridge with MockSource (fast anomaly_every=4, seed=42).
        Inject frames until an anomaly is produced.
        Assert a ComplianceEvent tx signature is returned from log_compliance
        (i.e. written on-chain) within 5 seconds.
        """
        rpc_url = os.environ.get("HELIUS_RPC_URL", "https://api.devnet.solana.com")
        program_id = os.environ.get("AUXIN_PROGRAM_ID")

        compliance_received: asyncio.Event = asyncio.Event()
        compliance_sigs: list[str] = []

        async with AuxinProgramClient.connect(rpc_url=rpc_url, program_id=program_id) as client:
            # Wrap log_compliance to capture the returned signature
            _original_log_compliance = client.log_compliance

            async def _intercepted_log_compliance(**kwargs):  # type: ignore[no-untyped-def]
                sig = await _original_log_compliance(**kwargs)
                compliance_sigs.append(sig)
                compliance_received.set()
                return sig

            client.log_compliance = _intercepted_log_compliance  # type: ignore[assignment]

            # MockSource with seed=42, anomaly_every=4 → first anomaly at frame ~4-7
            source = MockSource(rate_hz=0, anomaly_every=4, seed=42)

            # Oracle in fallback mode (no GEMINI_API_KEY required)
            oracle = SafetyOracle(api_key=None)

            broadcaster = _mock_broadcaster()

            bridge = Bridge(
                source=source,
                oracle=oracle,
                program_client=client,
                wallet=funded_wallet,
                ws_broadcaster=broadcaster,
                privacy_provider=DirectProvider(client),
                owner_pubkey=funded_wallet.pubkey,
                provider_pubkey=None,
                healthz_port=0,
            )

            # Run frame processor + compliance worker concurrently
            async def _process_frames() -> None:
                count = 0
                async for frame in source.stream():
                    await bridge.process(frame)
                    count += 1
                    if compliance_received.is_set() or count >= 30:
                        break

            frame_task = asyncio.create_task(_process_frames())
            worker_task = asyncio.create_task(bridge._compliance_worker())

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not compliance_received.is_set():
                await asyncio.sleep(0.1)

            frame_task.cancel()
            worker_task.cancel()
            await asyncio.gather(frame_task, worker_task, return_exceptions=True)

        # ── Assertions ────────────────────────────────────────────────────────
        assert compliance_sigs, (
            "No ComplianceEvent tx signature returned within 5 s. "
            "Check: program deployed? wallet funded? RPC reachable?"
        )

        sig = compliance_sigs[0]
        # Solana base58 signatures are 88 characters
        assert len(sig) == 88, f"Unexpected signature length ({len(sig)}): {sig!r}"

        print(f"\nComplianceEvent on-chain: https://explorer.solana.com/tx/{sig}?cluster=devnet")

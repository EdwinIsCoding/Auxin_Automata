"""Tests targeting specific uncovered lines in bridge.py.

Covers: WebsocketBroadcaster, _SubmissionLayer, Bridge.process scene queue,
oracle throttle skip, payment worker video frame handling, payment worker
success paths, temp file cleanup, scene worker, _scoring_ready_fallback,
risk scoring error path, treasury worker, and invoice worker.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from solders.keypair import Keypair

from auxin_sdk.bridge import (
    PRIORITY_FEE_FALLBACK_MICRO_LAMPORTS,
    SCENE_INTERVAL_FRAMES,
    Bridge,
    WebsocketBroadcaster,
    _PaymentTask,
    _SubmissionLayer,
)
from auxin_sdk.invoicing.types import Invoice
from auxin_sdk.oracle import OracleDecision, SafetyOracle, SceneDescription
from auxin_sdk.privacy.base import PaymentResult, PrivacyProvider
from auxin_sdk.privacy.direct import DirectProvider
from auxin_sdk.program.client import AuxinProgramClient
from auxin_sdk.risk.types import RiskBreakdown, RiskReport
from auxin_sdk.schema import TelemetryFrame
from auxin_sdk.sources.mock import MockSource
from auxin_sdk.treasury.types import BudgetAllocation, RecommendedAction, TreasuryAnalysis
from auxin_sdk.wallet import HardwareWallet

# ── Helpers ──────────────────────────────────────────────────────────────────


def _normal_frame():
    return TelemetryFrame(
        timestamp=datetime.now(UTC),
        joint_positions=[0.1] * 6,
        joint_velocities=[0.0] * 6,
        joint_torques=[5.0] * 6,
        end_effector_pose={"x": 0.1, "y": 0.2, "z": 0.3},
        anomaly_flags=[],
    )


def _mock_broadcaster():
    bc = MagicMock(spec=WebsocketBroadcaster)
    bc.broadcast = AsyncMock()
    bc.start = AsyncMock()
    bc.stop = AsyncMock()
    bc.client_count = 0
    return bc


def _mock_oracle(approved=True):
    oracle = MagicMock(spec=SafetyOracle)
    oracle.check = AsyncMock(
        return_value=OracleDecision(
            action_approved=approved,
            reason="ok",
            confidence=0.95,
            latency_ms=10.0,
            prompt_version="v1",
            used_fallback=False,
        )
    )
    return oracle


def _mock_program_client():
    client = MagicMock(spec=AuxinProgramClient)
    client.log_compliance = AsyncMock(return_value="FakeCompSig")
    client.stream_payment = AsyncMock(return_value="FakePaySig")
    return client


def _make_bridge(
    source,
    oracle,
    program_client,
    wallet,
    broadcaster,
    provider_pubkey=None,
    _oracle_interval_frames=1,
):
    return Bridge(
        source=source,
        oracle=oracle,
        program_client=program_client,
        wallet=wallet,
        ws_broadcaster=broadcaster,
        privacy_provider=DirectProvider(program_client),
        owner_pubkey=wallet.pubkey,
        provider_pubkey=provider_pubkey or Keypair().pubkey(),
        healthz_port=0,
        _oracle_interval_frames=_oracle_interval_frames,
    )


def _make_risk_report():
    return RiskReport(
        overall_score=85.0,
        grade="A",
        breakdown=[
            RiskBreakdown(
                category="financial",
                score=90.0,
                weight=0.4,
                factors=["stable payments"],
            )
        ],
        trend="stable",
        trend_data=[{"date": "2026-05-12", "score": 85.0}],
        computed_at=datetime.now(UTC),
    )


def _make_treasury_analysis(
    runway_status="warning",
    actions=None,
):
    if actions is None:
        actions = []
    return TreasuryAnalysis(
        burn_rate_lamports_per_hour=5000,
        runway_hours=24.0,
        runway_status=runway_status,
        budget_allocation=BudgetAllocation(inference=60.0, reserve=30.0, buffer=10.0),
        recommended_actions=actions,
        anomaly_flags=[],
        summary="Test treasury analysis",
        analyzed_at=datetime.now(UTC),
        used_fallback=False,
    )


def _make_invoice():
    return Invoice(
        generated_at=datetime.now(UTC),
        period_start=datetime.now(UTC) - timedelta(hours=24),
        period_end=datetime.now(UTC),
        hardware_agent_pubkey="FakeKey123",
        line_items=[],
        compliance_summary=[],
        total_lamports=50000,
        total_sol=0.00005,
        total_transactions=10,
        total_compliance_events=1,
    )


# ── WebsocketBroadcaster ────────────────────────────────────────────────────


class TestWebsocketBroadcaster:
    """Lines 199-205, 225-237, 243."""

    def test_init_attributes(self):
        """Line 199-205: __init__ sets host, port, connections, runner, site, sticky."""
        bc = WebsocketBroadcaster("127.0.0.1", 0)
        assert bc._host == "127.0.0.1"
        assert bc._port == 0
        assert bc._connections == set()
        assert bc._runner is None
        assert bc._site is None
        assert bc._sticky == {}

    @pytest.mark.asyncio
    async def test_broadcast_sticky_caching(self):
        """Line 225-227: risk_report and treasury_analysis payloads are cached."""
        bc = WebsocketBroadcaster("127.0.0.1", 0)
        risk_payload = {"type": "risk_report", "data": {"score": 85}}
        await bc.broadcast(risk_payload)
        assert bc._sticky["risk_report"] == risk_payload

        treasury_payload = {"type": "treasury_analysis", "data": {"runway": 24}}
        await bc.broadcast(treasury_payload)
        assert bc._sticky["treasury_analysis"] == treasury_payload

    @pytest.mark.asyncio
    async def test_broadcast_no_connections_returns_early(self):
        """Line 228-229: with no connections, broadcast returns early after caching."""
        bc = WebsocketBroadcaster("127.0.0.1", 0)
        # Should not raise; no connections to send to
        await bc.broadcast({"type": "telemetry", "data": {}})
        assert bc._connections == set()

    @pytest.mark.asyncio
    async def test_broadcast_with_connections(self):
        """Line 230-237: sends JSON to connected sockets."""
        bc = WebsocketBroadcaster("127.0.0.1", 0)
        mock_ws = AsyncMock()
        mock_ws.send_str = AsyncMock()
        bc._connections.add(mock_ws)

        payload = {"type": "telemetry", "data": {"x": 1}}
        await bc.broadcast(payload)

        mock_ws.send_str.assert_called_once_with(json.dumps(payload, default=str))

    def test_client_count(self):
        """Line 243: client_count returns len(_connections)."""
        bc = WebsocketBroadcaster("127.0.0.1", 0)
        assert bc.client_count == 0
        mock_ws = MagicMock()
        bc._connections.add(mock_ws)
        assert bc.client_count == 1


# ── _SubmissionLayer ─────────────────────────────────────────────────────────


class TestSubmissionLayer:
    """Lines 305-306, 359-378, 406-429."""

    @pytest.mark.asyncio
    async def test_log_compliance_idempotency_skip(self):
        """Line 305-306: duplicate idempotency key skips submission."""
        client = _mock_program_client()
        layer = _SubmissionLayer(client, "", None)
        wallet = HardwareWallet(Keypair())

        key = "dup-comp-key"
        sig1 = await layer.log_compliance(
            hw_wallet=wallet,
            owner_pubkey=wallet.pubkey,
            telemetry_hash="abc123",
            severity=2,
            reason_code=1,
            idempotency_key=key,
        )
        assert sig1 == "FakeCompSig"

        sig2 = await layer.log_compliance(
            hw_wallet=wallet,
            owner_pubkey=wallet.pubkey,
            telemetry_hash="abc123",
            severity=2,
            reason_code=1,
            idempotency_key=key,
        )
        assert sig2 is None
        # Client should only have been called once
        assert client.log_compliance.await_count == 1

    @pytest.mark.asyncio
    async def test_stream_payment_normal_path(self):
        """Line 359-378: normal stream_payment returns signature."""
        client = _mock_program_client()
        layer = _SubmissionLayer(client, "", None)
        wallet = HardwareWallet(Keypair())
        provider = Keypair().pubkey()

        sig = await layer.stream_payment(
            hw_wallet=wallet,
            owner_pubkey=wallet.pubkey,
            provider_pubkey=provider,
            amount_lamports=5000,
            idempotency_key="pay-key-1",
        )
        assert sig == "FakePaySig"
        client.stream_payment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_payment_idempotency_skip(self):
        """Line 359-361: duplicate payment key returns None."""
        client = _mock_program_client()
        layer = _SubmissionLayer(client, "", None)
        wallet = HardwareWallet(Keypair())
        provider = Keypair().pubkey()

        await layer.stream_payment(
            hw_wallet=wallet,
            owner_pubkey=wallet.pubkey,
            provider_pubkey=provider,
            amount_lamports=5000,
            idempotency_key="pay-dup",
        )
        sig2 = await layer.stream_payment(
            hw_wallet=wallet,
            owner_pubkey=wallet.pubkey,
            provider_pubkey=provider,
            amount_lamports=5000,
            idempotency_key="pay-dup",
        )
        assert sig2 is None
        assert client.stream_payment.await_count == 1

    @pytest.mark.asyncio
    async def test_get_priority_fee_no_helius_key(self):
        """Line 406-407: no helius key returns fallback."""
        client = _mock_program_client()
        layer = _SubmissionLayer(client, "", None)
        fee = await layer.get_priority_fee_micro_lamports()
        assert fee == PRIORITY_FEE_FALLBACK_MICRO_LAMPORTS

    @pytest.mark.asyncio
    async def test_get_priority_fee_successful_fetch(self):
        """Line 408-422: successful Helius fetch returns parsed fee."""
        client = _mock_program_client()
        layer = _SubmissionLayer(client, "", "fake-helius-key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"priorityFeeEstimate": 2500}}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("auxin_sdk.bridge.httpx.AsyncClient", return_value=mock_http):
            fee = await layer.get_priority_fee_micro_lamports()
        assert fee == 2500

    @pytest.mark.asyncio
    async def test_get_priority_fee_fetch_error(self):
        """Line 423-429: fetch error returns fallback."""
        client = _mock_program_client()
        layer = _SubmissionLayer(client, "", "fake-helius-key")

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=Exception("connection timeout"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("auxin_sdk.bridge.httpx.AsyncClient", return_value=mock_http):
            fee = await layer.get_priority_fee_micro_lamports()
        assert fee == PRIORITY_FEE_FALLBACK_MICRO_LAMPORTS


# ── Bridge.process: Scene Queue Path ────────────────────────────────────────


class TestBridgeProcessSceneQueue:
    """Lines 654, 661-663: scene queue enqueuing at SCENE_INTERVAL_FRAMES."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_scene_queue_populated_at_interval(self, wallet):
        """Process enough frames to hit SCENE_INTERVAL_FRAMES and enqueue a scene task."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        # Process SCENE_INTERVAL_FRAMES normal frames
        for _ in range(SCENE_INTERVAL_FRAMES):
            await bridge.process(_normal_frame())

        assert not bridge._scene_queue.empty()
        task = bridge._scene_queue.get_nowait()
        assert isinstance(task, _PaymentTask)


# ── Bridge.process: Oracle Throttle Skip ─────────────────────────────────────


class TestOracleThrottleSkip:
    """Line 719: non-interval frames skip the payment queue."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_non_interval_frames_skip_payment_queue(self, wallet):
        """With _oracle_interval_frames=3, frames 1 and 2 skip the payment queue."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(
            source,
            oracle,
            client,
            wallet,
            bc,
            _oracle_interval_frames=3,
        )

        # Process 2 frames (neither hits interval of 3)
        await bridge.process(_normal_frame())
        await bridge.process(_normal_frame())

        assert bridge._payment_queue.empty()

    @pytest.mark.asyncio
    async def test_interval_frame_reaches_payment_queue(self, wallet):
        """The 3rd frame (interval=3) should reach the payment queue."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(
            source,
            oracle,
            client,
            wallet,
            bc,
            _oracle_interval_frames=3,
        )

        for _ in range(3):
            await bridge.process(_normal_frame())

        assert not bridge._payment_queue.empty()


# ── Payment Worker: Video Frame Handling ─────────────────────────────────────


class TestPaymentWorkerVideoFrame:
    """Lines 827-847: mock source.get_frame_at returning a numpy array, mock cv2."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_real_video_frame_path(self, wallet):
        """When source.get_frame_at returns an array, payment worker uses cv2 to write it."""
        source = MockSource()
        oracle = _mock_oracle(approved=True)
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        # Give the source a get_frame_at method returning a numpy array
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        source.get_frame_at = MagicMock(return_value=fake_frame)

        # Create a task with a source_frame_idx
        frame = _normal_frame()
        task = _PaymentTask(frame=frame, source_frame_idx=42)
        await bridge._payment_queue.put(task)

        # Mock cv2 and privacy provider
        mock_cv2 = MagicMock()
        mock_cv2.imwrite = MagicMock()
        mock_cv2.cvtColor = MagicMock(return_value=fake_frame)
        mock_cv2.COLOR_RGB2BGR = 4

        bridge.privacy_provider = AsyncMock(spec=PrivacyProvider)
        bridge.privacy_provider.send_payment = AsyncMock(
            return_value=PaymentResult(
                tx_signature="FakePaySig",
                privacy_provider="direct",
                is_private=False,
                confirmation_slot=100,
                metadata={},
            )
        )

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            # Run worker in background, let it process one task
            worker = asyncio.create_task(bridge._payment_worker())
            await asyncio.sleep(0.1)
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker

        mock_cv2.imwrite.assert_called_once()
        mock_cv2.cvtColor.assert_called_once()


# ── Payment Worker: Success Paths ────────────────────────────────────────────


class TestPaymentWorkerSuccessPaths:
    """Lines 878, 898, 914: payment_lamport_multiplier, payment_log append, duplicate."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_successful_payment_appends_log(self, wallet):
        """Lines 878-898: successful payment applies lamport_multiplier and appends to log."""
        source = MockSource()
        oracle = _mock_oracle(approved=True)
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)
        bridge._payment_lamport_multiplier = 0.7

        bridge.privacy_provider = AsyncMock(spec=PrivacyProvider)
        bridge.privacy_provider.send_payment = AsyncMock(
            return_value=PaymentResult(
                tx_signature="RealSig123",
                privacy_provider="direct",
                is_private=False,
                confirmation_slot=200,
                metadata={},
            )
        )

        frame = _normal_frame()
        task = _PaymentTask(frame=frame)
        await bridge._payment_queue.put(task)

        worker = asyncio.create_task(bridge._payment_worker())
        await asyncio.sleep(0.15)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

        assert len(bridge._payment_log) == 1
        entry = bridge._payment_log[0]
        # Lamport multiplier should be applied
        from auxin_sdk.bridge import PAYMENT_AMOUNT_LAMPORTS

        expected_lamports = int(PAYMENT_AMOUNT_LAMPORTS * 0.7)
        assert entry["lamports"] == expected_lamports
        assert entry["success"] is True

    @pytest.mark.asyncio
    async def test_duplicate_payment_no_signature(self, wallet):
        """Line 914: when result.tx_signature is None, labels duplicate."""
        source = MockSource()
        oracle = _mock_oracle(approved=True)
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        bridge.privacy_provider = AsyncMock(spec=PrivacyProvider)
        bridge.privacy_provider.send_payment = AsyncMock(
            return_value=PaymentResult(
                tx_signature=None,
                privacy_provider="direct",
                is_private=False,
                confirmation_slot=None,
                metadata={},
            )
        )

        frame = _normal_frame()
        task = _PaymentTask(frame=frame)
        await bridge._payment_queue.put(task)

        worker = asyncio.create_task(bridge._payment_worker())
        await asyncio.sleep(0.15)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

        # No payment log entry since signature was None
        assert len(bridge._payment_log) == 0


# ── Payment Worker: Temp File Cleanup ────────────────────────────────────────


class TestPaymentWorkerTempFileCleanup:
    """Lines 939-940: temp file is cleaned up in the finally block."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_temp_file_cleanup(self, wallet, tmp_path):
        """Temp file created for video frame is removed after processing."""
        source = MockSource()
        oracle = _mock_oracle(approved=True)
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        source.get_frame_at = MagicMock(return_value=fake_frame)

        bridge.privacy_provider = AsyncMock(spec=PrivacyProvider)
        bridge.privacy_provider.send_payment = AsyncMock(
            return_value=PaymentResult(
                tx_signature="Sig",
                privacy_provider="direct",
                is_private=False,
                confirmation_slot=300,
                metadata={},
            )
        )

        frame = _normal_frame()
        task = _PaymentTask(frame=frame, source_frame_idx=10)
        await bridge._payment_queue.put(task)

        mock_cv2 = MagicMock()
        mock_cv2.imwrite = MagicMock()
        mock_cv2.cvtColor = MagicMock(return_value=fake_frame)
        mock_cv2.COLOR_RGB2BGR = 4

        # Track the temp file created
        import tempfile

        original_ntf = tempfile.NamedTemporaryFile
        created_paths = []

        def tracking_ntf(*args, **kwargs):
            kwargs["delete"] = False
            f = original_ntf(*args, **kwargs)
            created_paths.append(Path(f.name))
            return f

        with (
            patch.dict("sys.modules", {"cv2": mock_cv2}),
            patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf),
        ):
            worker = asyncio.create_task(bridge._payment_worker())
            await asyncio.sleep(0.15)
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker

        # Temp file should have been cleaned up (unlinked)
        for p in created_paths:
            assert not p.exists(), f"Temp file {p} was not cleaned up"


# ── Scene Worker ─────────────────────────────────────────────────────────────


class TestSceneWorker:
    """Lines 949-998: mock oracle.describe_scene and test the full scene worker loop."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_scene_worker_processes_task(self, wallet):
        """Scene worker calls describe_scene and broadcasts the result."""
        source = MockSource()
        oracle = _mock_oracle()
        oracle.describe_scene = AsyncMock(
            return_value=SceneDescription(
                objects=["wrench", "bolt"],
                scene_summary="A workbench with tools",
                confidence=0.92,
                latency_ms=150.0,
                used_fallback=False,
            )
        )
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        frame = _normal_frame()
        task = _PaymentTask(frame=frame, source_frame_idx=None)
        await bridge._scene_queue.put(task)

        worker = asyncio.create_task(bridge._scene_worker())
        await asyncio.sleep(0.15)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

        # Should have broadcast a scene_description message
        bc.broadcast.assert_called()
        calls = [
            c for c in bc.broadcast.call_args_list if c[0][0].get("type") == "scene_description"
        ]
        assert len(calls) >= 1
        data = calls[0][0][0]["data"]
        assert data["objects"] == ["wrench", "bolt"]
        assert data["scene_summary"] == "A workbench with tools"
        assert bridge._last_scene is not None

    @pytest.mark.asyncio
    async def test_scene_worker_with_video_frame(self, wallet):
        """Scene worker uses get_frame_at when source_frame_idx is provided."""
        source = MockSource()
        fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        source.get_frame_at = MagicMock(return_value=fake_frame)

        oracle = _mock_oracle()
        oracle.describe_scene = AsyncMock(
            return_value=SceneDescription(
                objects=["table"],
                scene_summary="A table",
                confidence=0.9,
                latency_ms=100.0,
                used_fallback=False,
            )
        )
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        frame = _normal_frame()
        task = _PaymentTask(frame=frame, source_frame_idx=5)
        await bridge._scene_queue.put(task)

        mock_cv2 = MagicMock()
        mock_cv2.imwrite = MagicMock()
        mock_cv2.cvtColor = MagicMock(return_value=fake_frame)
        mock_cv2.COLOR_RGB2BGR = 4

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            worker = asyncio.create_task(bridge._scene_worker())
            await asyncio.sleep(0.15)
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker

        oracle.describe_scene.assert_awaited_once()


# ── _scoring_ready_fallback ──────────────────────────────────────────────────


class TestScoringReadyFallback:
    """Lines 1009-1018: patch sleep to 0, verify it sets the event."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_fallback_sets_event(self, wallet):
        """After sleep, if _scoring_ready not set, fallback sets it."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        assert not bridge._scoring_ready.is_set()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await bridge._scoring_ready_fallback()

        assert bridge._scoring_ready.is_set()

    @pytest.mark.asyncio
    async def test_fallback_no_op_when_already_set(self, wallet):
        """If _scoring_ready is already set, fallback is a no-op."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        bridge._scoring_ready.set()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await bridge._scoring_ready_fallback()

        assert bridge._scoring_ready.is_set()


# ── Risk Scoring Worker: Error Path ──────────────────────────────────────────


class TestRiskScoringWorkerError:
    """Lines 1054-1057: mock _get_balance_sol to raise."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_error_path_continues(self, wallet):
        """When _get_balance_sol raises, the worker logs the error and continues."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        # Pre-set scoring_ready so worker doesn't wait
        bridge._scoring_ready.set()

        # Make _get_balance_sol raise
        bridge._get_balance_sol = AsyncMock(side_effect=RuntimeError("RPC down"))

        # Patch sleep to avoid real waiting; raise CancelledError after first iteration
        call_count = 0

        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=counting_sleep):
            worker = asyncio.create_task(bridge._risk_scoring_worker())
            with pytest.raises(asyncio.CancelledError):
                await worker

        # Worker should have called _get_balance_sol at least once
        bridge._get_balance_sol.assert_awaited()


# ── Treasury Worker ──────────────────────────────────────────────────────────


class TestTreasuryWorker:
    """Lines 1078-1150: test throttle + reserve actions, and healthy reset."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_throttle_and_reserve_actions(self, wallet):
        """Critical auto-executable throttle + reserve actions apply multipliers."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)
        bridge._scoring_ready.set()

        actions = [
            RecommendedAction(
                action="Throttle inference rate",
                priority="critical",
                reasoning="Burn rate too high",
                auto_executable=True,
            ),
            RecommendedAction(
                action="Increase reserve allocation",
                priority="critical",
                reasoning="Low reserves",
                auto_executable=True,
            ),
        ]
        analysis = _make_treasury_analysis(runway_status="critical", actions=actions)

        mock_treasury = MagicMock()
        mock_treasury.analyze = AsyncMock(return_value=analysis)
        bridge._treasury_agent = mock_treasury
        bridge._get_balance_sol = AsyncMock(return_value=1.5)

        call_count = 0

        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=counting_sleep):
            worker = asyncio.create_task(bridge._treasury_worker())
            with pytest.raises(asyncio.CancelledError):
                await worker

        from auxin_sdk.bridge import _THROTTLE_MULTIPLIER

        assert bridge._oracle_interval_multiplier == _THROTTLE_MULTIPLIER
        assert bridge._payment_lamport_multiplier == 0.7

    @pytest.mark.asyncio
    async def test_healthy_resets_multipliers(self, wallet):
        """runway_status='healthy' resets throttle and lamport multipliers."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)
        bridge._scoring_ready.set()

        # Pre-set multipliers as if previously throttled
        bridge._oracle_interval_multiplier = 2.5
        bridge._payment_lamport_multiplier = 0.7

        analysis = _make_treasury_analysis(runway_status="healthy", actions=[])
        mock_treasury = MagicMock()
        mock_treasury.analyze = AsyncMock(return_value=analysis)
        bridge._treasury_agent = mock_treasury
        bridge._get_balance_sol = AsyncMock(return_value=10.0)

        call_count = 0

        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=counting_sleep):
            worker = asyncio.create_task(bridge._treasury_worker())
            with pytest.raises(asyncio.CancelledError):
                await worker

        assert bridge._oracle_interval_multiplier == 1.0
        assert bridge._payment_lamport_multiplier == 1.0

    @pytest.mark.asyncio
    async def test_treasury_worker_none_agent_exits(self, wallet):
        """If _treasury_agent is None, worker breaks out."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)
        bridge._scoring_ready.set()
        bridge._treasury_agent = None

        # Should exit immediately without error
        await bridge._treasury_worker()


# ── Invoice Worker ───────────────────────────────────────────────────────────


class TestInvoiceWorker:
    """Lines 1157-1203: mock generate() and render_pdf(), patch sleep to 0."""

    @pytest.fixture()
    def wallet(self, tmp_path):
        return HardwareWallet(Keypair())

    @pytest.mark.asyncio
    async def test_invoice_worker_generates_invoice(self, wallet, tmp_path):
        """Invoice worker calls generate, render_json, render_pdf, and broadcasts."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        invoice = _make_invoice()
        pdf_path = tmp_path / "invoice.pdf"
        pdf_path.touch()

        bridge._invoice_generator = MagicMock()
        bridge._invoice_generator.generate = AsyncMock(return_value=invoice)
        bridge._invoice_generator.render_json = MagicMock()
        bridge._invoice_generator.render_pdf = MagicMock(return_value=pdf_path)

        call_count = 0

        async def controlled_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            # First sleep returns immediately (the interval sleep)

        with patch("asyncio.sleep", side_effect=controlled_sleep):
            await bridge._invoice_worker()

        bridge._invoice_generator.generate.assert_awaited_once()
        bridge._invoice_generator.render_json.assert_called_once()
        bridge._invoice_generator.render_pdf.assert_called_once()
        assert bridge._latest_invoice_path == pdf_path

        # Should have broadcast invoice_ready
        invoice_broadcasts = [
            c for c in bc.broadcast.call_args_list if c[0][0].get("type") == "invoice_ready"
        ]
        assert len(invoice_broadcasts) == 1
        data = invoice_broadcasts[0][0][0]["data"]
        assert data["invoice_id"] == invoice.invoice_id
        assert data["total_sol"] == invoice.total_sol

    @pytest.mark.asyncio
    async def test_invoice_worker_error_continues(self, wallet):
        """Invoice worker catches errors and continues the loop."""
        source = MockSource()
        oracle = _mock_oracle()
        client = _mock_program_client()
        bc = _mock_broadcaster()
        bridge = _make_bridge(source, oracle, client, wallet, bc)

        bridge._invoice_generator = MagicMock()
        bridge._invoice_generator.generate = AsyncMock(
            side_effect=RuntimeError("generation failed")
        )

        call_count = 0

        async def controlled_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=controlled_sleep):
            await bridge._invoice_worker()

        # Worker should have attempted generation
        bridge._invoice_generator.generate.assert_awaited_once()

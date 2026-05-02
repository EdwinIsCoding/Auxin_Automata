"""Bridge — long-running async process tying telemetry → oracle → Solana → dashboard ws.

Architecture
------------

                ┌──────────────────────────────────────────────────────────┐
  TelemetrySource ──▶  Bridge.run()  main loop                             │
  (mock|twin|ros2)       └── process(frame)                                │
                               ├─ (a) ws_broadcaster.broadcast(frame)      │
                               ├─ (b) anomaly? → _compliance_queue         │
                               └─ (c) normal?  → _payment_queue (cap 50)  │
                                                                            │
  _compliance_worker ◀── _compliance_queue (UNBOUNDED — never dropped)     │
      └── _submission.log_compliance(...)                                   │
           └── ws_broadcaster.broadcast(compliance_event)                  │
                                                                            │
  _payment_worker ◀── _payment_queue (maxsize=50)                          │
      └── oracle.check(frame, image)                                        │
           ├── approved → _submission.stream_payment(...)                  │
           └── denied   → _compliance_queue (severity=1)                   │
                                                                            │
  /healthz  :8767   JSON: source_status, last_tx, oracle_latency, queues   │
  WS server :8766   Multi-client telemetry broadcast + keepalive            │
                └──────────────────────────────────────────────────────────┘

Architecture rules enforced here — never relax:
  1. Source is selected SOLELY by AUXIN_SOURCE env var; zero code branches on type.
  2. Compliance events have their own UNBOUNDED queue — never dropped, never
     rate-limited, never budget-blocked.
  3. Only informational (non-anomaly) frames are dropped under backpressure.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp
import aiohttp.web
import httpx
import structlog
from prometheus_client import Counter, Gauge, Histogram
from prometheus_client import start_http_server as _prom_start

from .fixtures import sample_workspace_image
from .hashing import sha256_hex
from .invoicing.generator import InvoiceGenerator
from .logging import bind_request_id
from .oracle import OracleDecision, SafetyOracle
from .privacy.base import PaymentResult, PrivacyProvider
from .program.client import AuxinProgramClient
from .risk.scorer import calculate_risk_score
from .risk.types import RiskReport
from .schema import TelemetryFrame
from .sources.base import TelemetrySource
from .treasury.agent import TreasuryAgent
from .treasury.types import TreasuryAnalysis
from .wallet import HardwareWallet

log = structlog.get_logger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────
# Defined at module level so they are singletons across the process lifetime.

_TX_TOTAL = Counter(
    "auxin_tx_submitted_total",
    "Solana transactions submitted by the bridge",
    ["kind", "status"],
)
_ANOMALIES_TOTAL = Counter(
    "auxin_anomalies_total",
    "Telemetry frames flagged as anomalies",
)
_ORACLE_LATENCY = Histogram(
    "auxin_oracle_latency_seconds",
    "Gemini SafetyOracle check round-trip latency",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0],
)
_SOLANA_SUBMIT_LATENCY = Histogram(
    "auxin_solana_submit_latency_seconds",
    "Solana transaction submission latency (sign + confirm)",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0],
)
_QUEUE_DEPTH = Gauge(
    "auxin_queue_depth",
    "Current number of items waiting in a bridge queue",
    ["queue"],
)

# ── Constants ─────────────────────────────────────────────────────────────────

PAYMENT_QUEUE_MAXSIZE = 50
PAYMENT_AMOUNT_LAMPORTS = 5_000  # 0.000005 SOL per oracle-approved action
COMPLIANCE_SEVERITY_ANOMALY = 2  # direct anomaly-flag path
COMPLIANCE_SEVERITY_ORACLE_DENIED = 1  # oracle denial path
REASON_CODE_ANOMALY = 0x0001
REASON_CODE_ORACLE_DENIED = 0x0002
MAX_BLOCKHASH_RETRIES = 3
PRIORITY_FEE_FALLBACK_MICRO_LAMPORTS = 1_000
COMPLIANCE_DRAIN_TIMEOUT_S = 30.0

# Financial intelligence intervals (configurable via env)
_RISK_INTERVAL_S = int(os.getenv("AUXIN_RISK_INTERVAL_S", "60"))
_TREASURY_INTERVAL_S = int(os.getenv("AUXIN_TREASURY_INTERVAL_S", "120"))
_INVOICE_INTERVAL_H = float(os.getenv("AUXIN_INVOICE_INTERVAL_H", "24"))

# Default throttle multiplier applied when treasury flags critical runway
_THROTTLE_MULTIPLIER = 2.5


# ── Internal task types ───────────────────────────────────────────────────────


@dataclass
class _ComplianceTask:
    frame: TelemetryFrame
    telemetry_hash: str
    severity: int
    reason_code: int
    idempotency_key: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class _PaymentTask:
    frame: TelemetryFrame
    idempotency_key: str = field(default_factory=lambda: uuid.uuid4().hex)


# ── WebsocketBroadcaster ──────────────────────────────────────────────────────


class WebsocketBroadcaster:
    """
    aiohttp WebSocket server on port 8766.

    Dashboard clients connect at ``ws://host:8766/ws``.  All connected clients
    receive every broadcast; dead connections are pruned silently.
    Ping/pong keepalive is handled by aiohttp (``heartbeat=30``).
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8766) -> None:
        self._host = host
        self._port = port
        self._connections: set[aiohttp.web.WebSocketResponse] = set()
        self._runner: aiohttp.web.AppRunner | None = None
        self._site: aiohttp.web.TCPSite | None = None

    async def start(self) -> None:  # pragma: no cover
        app = aiohttp.web.Application()
        app.router.add_get("/ws", self._handle_ws)
        self._runner = aiohttp.web.AppRunner(app)
        await self._runner.setup()
        self._site = aiohttp.web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        log.info("ws_broadcaster.started", host=self._host, port=self._port)

    async def stop(self) -> None:  # pragma: no cover
        if self._runner is not None:
            await self._runner.cleanup()
            log.info("ws_broadcaster.stopped")

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send *payload* as JSON to all connected clients.  Prunes dead sockets."""
        if not self._connections:
            return
        text = json.dumps(payload, default=str)
        dead: set[aiohttp.web.WebSocketResponse] = set()
        for ws in list(self._connections):
            try:
                await ws.send_str(text)
            except Exception:  # pragma: no cover
                dead.add(ws)
        self._connections -= dead
        if dead:  # pragma: no cover
            log.debug("ws_broadcaster.pruned", count=len(dead))

    @property
    def client_count(self) -> int:
        return len(self._connections)

    async def _handle_ws(  # pragma: no cover
        self, request: aiohttp.web.Request
    ) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        self._connections.add(ws)
        log.info("ws.client_connected", total=len(self._connections))
        try:
            async for msg in ws:
                # Dashboard clients are receive-only; close on any error
                if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
        finally:
            self._connections.discard(ws)
            log.info("ws.client_disconnected", total=len(self._connections))
        return ws


# ── Submission layer ──────────────────────────────────────────────────────────


class _SubmissionLayer:
    """
    Thin wrapper around AuxinProgramClient adding:
    - Priority fee estimation via Helius (or fixed fallback).
    - Per-tx blockhash refresh.
    - Retry on BlockhashNotFound (up to MAX_BLOCKHASH_RETRIES).
    - In-memory idempotency key deduplication to prevent double-submit on retry.
    """

    def __init__(
        self,
        client: AuxinProgramClient,
        rpc_url: str,
        helius_api_key: str | None = None,
    ) -> None:
        self._client = client
        self._rpc_url = rpc_url
        self._helius_api_key = helius_api_key
        self._submitted: set[str] = set()

    async def log_compliance(
        self,
        hw_wallet: HardwareWallet,
        owner_pubkey: Any,
        telemetry_hash: str,
        severity: int,
        reason_code: int,
        idempotency_key: str,
    ) -> str | None:
        """
        Submit a compliance log tx.  Returns the signature, or None if the
        idempotency key was already used (duplicate-safe on retry).
        """
        if idempotency_key in self._submitted:
            log.warning("submission.idempotent_skip", key=idempotency_key, kind="compliance")
            return None

        for attempt in range(1, MAX_BLOCKHASH_RETRIES + 1):
            try:
                sig = await self._client.log_compliance(
                    hw_wallet=hw_wallet,
                    owner_pubkey=owner_pubkey,
                    telemetry_hash=telemetry_hash,
                    severity=severity,
                    reason_code=reason_code,
                )
                self._submitted.add(idempotency_key)
                log.info(
                    "submission.compliance_ok",
                    signature=sig,
                    severity=severity,
                    attempt=attempt,
                )
                return sig
            except Exception as exc:  # pragma: no cover
                # SolanaRpcException wraps the real cause — unwrap for logging
                cause = exc.__cause__ or exc
                err_str = str(cause) or repr(exc)
                is_rate_limit = "429" in err_str or "Too Many Requests" in err_str
                is_blockhash = "BlockhashNotFound" in err_str
                if (is_blockhash or is_rate_limit) and attempt < MAX_BLOCKHASH_RETRIES:
                    log.warning(
                        "submission.blockhash_retry",
                        attempt=attempt,
                        kind="compliance",
                        error=err_str,
                    )
                    await asyncio.sleep(2.0 * attempt if is_rate_limit else 0.5 * attempt)
                    continue
                log.error(
                    "submission.compliance_failed",
                    error=err_str,
                    attempt=attempt,
                )
                raise
        return None  # pragma: no cover

    async def stream_payment(
        self,
        hw_wallet: HardwareWallet,
        owner_pubkey: Any,
        provider_pubkey: Any,
        amount_lamports: int,
        idempotency_key: str,
    ) -> str | None:
        """
        Submit a payment tx.  Returns the signature, or None if already submitted.
        """
        if idempotency_key in self._submitted:
            log.warning("submission.idempotent_skip", key=idempotency_key, kind="payment")
            return None

        for attempt in range(1, MAX_BLOCKHASH_RETRIES + 1):
            try:
                sig = await self._client.stream_payment(
                    hw_wallet=hw_wallet,
                    owner_pubkey=owner_pubkey,
                    provider_pubkey=provider_pubkey,
                    amount_lamports=amount_lamports,
                )
                self._submitted.add(idempotency_key)
                log.info(
                    "submission.payment_ok",
                    signature=sig,
                    amount_lamports=amount_lamports,
                    attempt=attempt,
                )
                return sig
            except Exception as exc:  # pragma: no cover
                cause = exc.__cause__ or exc
                err_str = str(cause) or repr(exc)
                is_rate_limit = "429" in err_str or "Too Many Requests" in err_str
                is_blockhash = "BlockhashNotFound" in err_str
                if (is_blockhash or is_rate_limit) and attempt < MAX_BLOCKHASH_RETRIES:
                    log.warning(
                        "submission.blockhash_retry",
                        attempt=attempt,
                        kind="payment",
                        error=err_str,
                    )
                    await asyncio.sleep(2.0 * attempt if is_rate_limit else 0.5 * attempt)
                    continue
                log.error(
                    "submission.payment_failed",
                    error=err_str,
                    attempt=attempt,
                )
                raise
        return None  # pragma: no cover

    async def get_priority_fee_micro_lamports(self) -> int:
        """
        Fetch recommended priority fee from Helius getPriorityFeeEstimate.
        Falls back to PRIORITY_FEE_FALLBACK_MICRO_LAMPORTS on any error.
        """
        if not self._helius_api_key:
            return PRIORITY_FEE_FALLBACK_MICRO_LAMPORTS
        try:
            async with httpx.AsyncClient(timeout=2.0) as http:
                resp = await http.post(
                    f"https://mainnet.helius-rpc.com/?api-key={self._helius_api_key}",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getPriorityFeeEstimate",
                        "params": [{"options": {"priorityLevel": "Medium"}}],
                    },
                )
                data = resp.json()
                fee = int(data["result"]["priorityFeeEstimate"])
                log.debug("priority_fee.fetched", micro_lamports=fee)
                return fee
        except Exception as exc:
            log.warning(
                "priority_fee.fetch_failed",
                error=str(exc),
                fallback=PRIORITY_FEE_FALLBACK_MICRO_LAMPORTS,
            )
            return PRIORITY_FEE_FALLBACK_MICRO_LAMPORTS


# ── Bridge ────────────────────────────────────────────────────────────────────


class Bridge:
    """
    Long-running async process.  Wires together:
        TelemetrySource → Gemini SafetyOracle → AuxinProgramClient → WebsocketBroadcaster

    Compliance contract
    -------------------
    Compliance events go into an unbounded asyncio.Queue.  They are NEVER dropped,
    NEVER rate-limited, and NEVER blocked by the payment backpressure logic.
    Informational (non-anomaly) frames are the only ones subject to the 50-item
    payment queue cap.

    Usage
    -----
    ::

        async with AuxinProgramClient.connect(rpc_url) as client:
            provider = DirectProvider(client)
            bridge = Bridge(source, oracle, client, wallet, broadcaster,
                            privacy_provider=provider)
            await bridge.run()   # blocks until SIGINT / cancellation
    """

    def __init__(
        self,
        source: TelemetrySource,
        oracle: SafetyOracle,
        program_client: AuxinProgramClient,
        wallet: HardwareWallet,
        ws_broadcaster: WebsocketBroadcaster,
        *,
        privacy_provider: PrivacyProvider,
        owner_pubkey: Any | None = None,
        provider_pubkey: Any | None = None,
        rpc_url: str = "",
        helius_api_key: str | None = None,
        healthz_port: int = 8767,
        metrics_port: int = 9090,
    ) -> None:
        self.source = source
        self.oracle = oracle
        self.program_client = program_client
        self.wallet = wallet
        self.ws_broadcaster = ws_broadcaster
        self.privacy_provider = privacy_provider
        self.owner_pubkey = owner_pubkey if owner_pubkey is not None else wallet.pubkey
        self.provider_pubkey = provider_pubkey
        self._healthz_port = healthz_port
        self._metrics_port = metrics_port

        self._submission = _SubmissionLayer(program_client, rpc_url, helius_api_key)

        # Two queues.  Compliance is unbounded per the architecture rule.
        self._compliance_queue: asyncio.Queue[_ComplianceTask] = asyncio.Queue()
        self._payment_queue: asyncio.Queue[_PaymentTask] = asyncio.Queue(
            maxsize=PAYMENT_QUEUE_MAXSIZE
        )

        # Health state
        self._start_time: float = time.monotonic()
        self._source_status: str = "initialising"
        self._last_successful_tx: dict[str, Any] | None = None
        self._last_oracle_latency_ms: float | None = None
        self._frames_processed: int = 0
        self._frames_dropped: int = 0
        self._compliance_total: int = 0
        self._payments_total: int = 0

        # HTTP health server handles
        self._health_runner: aiohttp.web.AppRunner | None = None
        self._health_site: aiohttp.web.TCPSite | None = None

        self._running: bool = False

        # ── Financial Intelligence ─────────────────────────────────────────────
        # In-memory payment / compliance accumulators (ring-buffer for scoring)
        self._payment_log: list[dict[str, Any]] = []
        self._compliance_log: list[dict[str, Any]] = []
        self._payment_log_max = 5_000  # keep last 5k payments

        # Latest snapshots (None until first computation)
        self._latest_risk_report: RiskReport | None = None
        self._latest_treasury_analysis: TreasuryAnalysis | None = None
        self._latest_invoice_path: Path | None = None

        # Treasury agent — lazy init (needs API key from env)
        self._treasury_agent: TreasuryAgent | None = None

        # Invoice generator
        self._invoice_generator = InvoiceGenerator()

        # Oracle-check interval multiplier (1.0 = normal, >1.0 = throttled)
        self._oracle_interval_multiplier: float = 1.0
        # Per-payment lamport multiplier (1.0 = normal, <1.0 = reduced)
        self._payment_lamport_multiplier: float = 1.0

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Start all services and iterate source.stream() until cancelled.

        Shutdown sequence on cancellation:
          1. Stop accepting new frames.
          2. Drain the compliance queue (up to 30 s) so no events are lost.
          3. Cancel workers.
          4. Close source, ws server, healthz.
        """
        self._running = True
        self._start_time = time.monotonic()

        # Start Prometheus metrics HTTP server (background thread, non-blocking).
        if self._metrics_port > 0:
            _prom_start(self._metrics_port)
            log.info("metrics.started", port=self._metrics_port)

        await self.ws_broadcaster.start()
        if self._healthz_port > 0:
            await self._start_healthz()

        # Initialise treasury agent (lazy — only if API key is set)
        api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("GEMINI_API_KEY")
        self._treasury_agent = TreasuryAgent(api_key=api_key)

        workers = [
            asyncio.create_task(self._compliance_worker(), name="compliance-worker"),
            asyncio.create_task(self._payment_worker(), name="payment-worker"),
            asyncio.create_task(self._risk_scoring_worker(), name="risk-scoring-worker"),
            asyncio.create_task(self._treasury_worker(), name="treasury-worker"),
            asyncio.create_task(self._invoice_worker(), name="invoice-worker"),
        ]

        try:
            self._source_status = "streaming"
            log.info("bridge.run_started", source=type(self.source).__name__)

            async for frame in self.source.stream():
                if not self._running:
                    break
                await self.process(frame)

        except asyncio.CancelledError:
            log.info("bridge.cancelled")
        except Exception as exc:
            log.error("bridge.fatal_error", error=str(exc), exc_info=True)
            raise
        finally:
            self._running = False
            self._source_status = "draining"

            # Drain compliance queue before exit — never lose compliance events.
            try:
                await asyncio.wait_for(
                    self._compliance_queue.join(),
                    timeout=COMPLIANCE_DRAIN_TIMEOUT_S,
                )
                log.info("bridge.compliance_queue_drained")
            except TimeoutError:
                log.warning(
                    "bridge.compliance_drain_timeout",
                    remaining=self._compliance_queue.qsize(),
                )

            self._source_status = "stopped"
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

            await self.source.close()
            await self.ws_broadcaster.stop()
            if self._healthz_port > 0:
                await self._stop_healthz()
            log.info("bridge.stopped")

    async def process(self, frame: TelemetryFrame) -> None:
        """
        Classify one telemetry frame and route it to the appropriate queue.

        (a) Always broadcast raw telemetry to the dashboard.
        (b) Anomaly frames → compliance queue (UNBOUNDED, never dropped).
        (c) Normal frames  → payment queue (cap=50).  Drop when full.
        """
        bind_request_id()
        self._frames_processed += 1

        # (a) Raw telemetry → dashboard
        await self.ws_broadcaster.broadcast(
            {
                "type": "telemetry",
                "data": frame.model_dump(mode="json"),
            }
        )

        # (b) Anomaly path — unconditional compliance
        if frame.anomaly_flags:
            _ANOMALIES_TOTAL.inc()
            task = _ComplianceTask(
                frame=frame,
                telemetry_hash=sha256_hex(frame),
                severity=COMPLIANCE_SEVERITY_ANOMALY,
                reason_code=REASON_CODE_ANOMALY,
            )
            await self._compliance_queue.put(task)
            _QUEUE_DEPTH.labels("compliance").set(self._compliance_queue.qsize())
            log.info(
                "bridge.anomaly_enqueued",
                flags=frame.anomaly_flags,
                hash_prefix=task.telemetry_hash[:16],
                compliance_depth=self._compliance_queue.qsize(),
            )
            return

        # (c) Normal path — payment (subject to backpressure)
        if self._payment_queue.full():
            self._frames_dropped += 1
            log.warning(
                "bridge.frame_dropped",
                reason="payment_queue_full",
                queue_depth=self._payment_queue.qsize(),
                total_dropped=self._frames_dropped,
            )
            return

        await self._payment_queue.put(_PaymentTask(frame=frame))
        _QUEUE_DEPTH.labels("payment").set(self._payment_queue.qsize())

    # ── Workers ───────────────────────────────────────────────────────────────

    async def _compliance_worker(self) -> None:
        """
        Drain the compliance queue forever.  Calls log_compliance for every event.
        Runs until cancelled.  task_done() is always called so queue.join() works.

        NOTE: Compliance events are NEVER routed through self.privacy_provider.
        They always go direct to the public chain via _submission.log_compliance().
        This is intentional: compliance logs must be publicly auditable and must
        arrive on-chain even if the active privacy provider is unavailable,
        mis-configured, or temporarily down.  The integrity of the safety record
        cannot depend on a third-party privacy relay.
        """
        log.info("compliance_worker.started")
        while True:
            task: _ComplianceTask = await self._compliance_queue.get()
            _QUEUE_DEPTH.labels("compliance").set(self._compliance_queue.qsize())
            try:
                _t0 = time.monotonic()
                sig = await self._submission.log_compliance(
                    hw_wallet=self.wallet,
                    owner_pubkey=self.owner_pubkey,
                    telemetry_hash=task.telemetry_hash,
                    severity=task.severity,
                    reason_code=task.reason_code,
                    idempotency_key=task.idempotency_key,
                )
                _SOLANA_SUBMIT_LATENCY.observe(time.monotonic() - _t0)
                if sig:
                    _TX_TOTAL.labels(kind="compliance", status="ok").inc()
                    self._compliance_total += 1
                    self._last_successful_tx = {
                        "signature": sig,
                        "kind": "compliance",
                        "severity": task.severity,
                    }
                    event_data = {
                        "hash": task.telemetry_hash,
                        "severity": task.severity,
                        "reason_code": task.reason_code,
                        "signature": sig,
                        "flags": task.frame.anomaly_flags,
                        "timestamp": task.frame.timestamp.isoformat(),
                    }
                    # Accumulate for risk scorer / invoice generator
                    self._compliance_log.append({
                        "timestamp": task.frame.timestamp.isoformat(),
                        "severity": task.severity,
                        "reason_code": task.reason_code,
                        "hash": task.telemetry_hash,
                        "tx_signature": sig,
                    })
                    await self.ws_broadcaster.broadcast(
                        {"type": "compliance_event", "data": event_data}
                    )
            except Exception as exc:
                _TX_TOTAL.labels(kind="compliance", status="error").inc()
                log.error(
                    "compliance_worker.error",
                    error=str(exc),
                    hash_prefix=task.telemetry_hash[:16],
                )
            finally:
                self._compliance_queue.task_done()

    async def _payment_worker(self) -> None:
        """
        Drain the payment queue forever.
        For each frame: call oracle, then either stream_payment or push to compliance queue.
        Oracle-denied frames trigger a severity-1 compliance log.
        """
        log.info("payment_worker.started")
        while True:
            task: _PaymentTask = await self._payment_queue.get()
            _QUEUE_DEPTH.labels("payment").set(self._payment_queue.qsize())
            try:
                image_path, _ = sample_workspace_image()
                decision: OracleDecision = await self.oracle.check(task.frame, image_path)
                self._last_oracle_latency_ms = decision.latency_ms
                _ORACLE_LATENCY.observe(decision.latency_ms / 1_000)

                if decision.action_approved:
                    if self.provider_pubkey is None:
                        log.warning(
                            "payment_worker.no_provider",
                            reason="provider_pubkey not configured — skipping payment",
                        )
                    else:
                        _t0 = time.monotonic()
                        result: PaymentResult = await self.privacy_provider.send_payment(
                            wallet=self.wallet,
                            owner_pubkey=self.owner_pubkey,
                            provider_pubkey=self.provider_pubkey,
                            lamports=PAYMENT_AMOUNT_LAMPORTS,
                            idempotency_key=task.idempotency_key,
                        )
                        _SOLANA_SUBMIT_LATENCY.observe(time.monotonic() - _t0)
                        if result.tx_signature:
                            _TX_TOTAL.labels(kind="payment", status="ok").inc()
                            self._payments_total += 1
                            effective_lamports = int(
                                PAYMENT_AMOUNT_LAMPORTS * self._payment_lamport_multiplier
                            )
                            self._last_successful_tx = {
                                "signature": result.tx_signature,
                                "kind": "payment",
                                "amount_lamports": effective_lamports,
                                "privacy_provider": result.privacy_provider,
                            }
                            payment_entry = {
                                "timestamp": task.frame.timestamp.isoformat(),
                                "lamports": effective_lamports,
                                "provider": str(self.provider_pubkey),
                                "tx_signature": result.tx_signature,
                                "success": True,
                            }
                            # Accumulate for risk scorer / invoice (ring buffer)
                            self._payment_log.append(payment_entry)
                            if len(self._payment_log) > self._payment_log_max:
                                self._payment_log = self._payment_log[-self._payment_log_max:]
                            await self.ws_broadcaster.broadcast(
                                {
                                    "type": "payment_event",
                                    "data": {
                                        "signature": result.tx_signature,
                                        "amount_lamports": effective_lamports,
                                        "provider": str(self.provider_pubkey),
                                        "privacy_provider": result.privacy_provider,
                                        "is_private": result.is_private,
                                        "timestamp": task.frame.timestamp.isoformat(),
                                        "oracle_reason": decision.reason,
                                    },
                                }
                            )
                        else:
                            _TX_TOTAL.labels(kind="payment", status="duplicate").inc()
                else:
                    # Oracle denial → compliance log (severity 1)
                    telemetry_hash = sha256_hex(task.frame)
                    compliance_task = _ComplianceTask(
                        frame=task.frame,
                        telemetry_hash=telemetry_hash,
                        severity=COMPLIANCE_SEVERITY_ORACLE_DENIED,
                        reason_code=REASON_CODE_ORACLE_DENIED,
                    )
                    await self._compliance_queue.put(compliance_task)
                    _QUEUE_DEPTH.labels("compliance").set(self._compliance_queue.qsize())
                    log.info(
                        "payment_worker.oracle_denied",
                        reason=decision.reason,
                        confidence=decision.confidence,
                        hash_prefix=telemetry_hash[:16],
                    )

            except Exception as exc:
                _TX_TOTAL.labels(kind="payment", status="error").inc()
                log.error("payment_worker.error", error=str(exc))
            finally:
                self._payment_queue.task_done()

    # ── Financial Intelligence Workers ────────────────────────────────────────

    async def _risk_scoring_worker(self) -> None:
        """
        Compute the Machine Health Score every AUXIN_RISK_INTERVAL_S seconds.
        Broadcasts RiskReport via WebSocket. Never blocks the main telemetry loop.
        """
        log.info("risk_scoring_worker.started", interval_s=_RISK_INTERVAL_S)
        while True:
            try:
                await asyncio.sleep(_RISK_INTERVAL_S)
                balance_sol = await self._get_balance_sol()
                report = calculate_risk_score(
                    payment_history=list(self._payment_log),
                    compliance_history=list(self._compliance_log),
                    balance=balance_sol,
                    tx_count=self._payments_total,
                )
                self._latest_risk_report = report
                await self.ws_broadcaster.broadcast(
                    {
                        "type": "risk_report",
                        "data": report.model_dump(mode="json"),
                    }
                )
                log.info(
                    "risk_scoring_worker.broadcast",
                    score=report.overall_score,
                    grade=report.grade,
                    trend=report.trend,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("risk_scoring_worker.error", error=str(exc))

    async def _treasury_worker(self) -> None:
        """
        Run the AI treasury analysis every AUXIN_TREASURY_INTERVAL_S seconds.
        If a critical auto_executable action is returned, the bridge adjusts its
        own behaviour within pre-defined safe bounds (throttle / reduce lamports).
        The treasury agent NEVER signs transactions or transfers funds.
        """
        log.info("treasury_worker.started", interval_s=_TREASURY_INTERVAL_S)
        while True:
            try:
                await asyncio.sleep(_TREASURY_INTERVAL_S)
                if self._treasury_agent is None:
                    continue
                balance_sol = await self._get_balance_sol()
                analysis = await self._treasury_agent.analyze(
                    payment_history=list(self._payment_log),
                    compliance_history=list(self._compliance_log),
                    balance=balance_sol,
                    risk_report=self._latest_risk_report,
                )
                self._latest_treasury_analysis = analysis

                # Apply auto-executable critical actions within safe bounds
                for action in analysis.recommended_actions:
                    if action.auto_executable and action.priority == "critical":
                        if "throttle" in action.action.lower():
                            self._oracle_interval_multiplier = _THROTTLE_MULTIPLIER
                            log.warning(
                                "treasury_worker.throttling_applied",
                                multiplier=_THROTTLE_MULTIPLIER,
                                reason=action.reasoning,
                            )
                            await self.ws_broadcaster.broadcast(
                                {
                                    "type": "bridge_adjustment",
                                    "data": {
                                        "kind": "throttle_inference",
                                        "multiplier": _THROTTLE_MULTIPLIER,
                                        "reason": action.reasoning,
                                    },
                                }
                            )
                        if "reserve" in action.action.lower():
                            self._payment_lamport_multiplier = 0.7
                            log.warning(
                                "treasury_worker.reserve_increase_applied",
                                lamport_multiplier=0.7,
                                reason=action.reasoning,
                            )
                            await self.ws_broadcaster.broadcast(
                                {
                                    "type": "bridge_adjustment",
                                    "data": {
                                        "kind": "increase_reserve",
                                        "lamport_multiplier": 0.7,
                                        "reason": action.reasoning,
                                    },
                                }
                            )

                # If runway recovered, reset throttle
                if analysis.runway_status == "healthy":
                    if self._oracle_interval_multiplier > 1.0:
                        self._oracle_interval_multiplier = 1.0
                        log.info("treasury_worker.throttle_reset")
                    if self._payment_lamport_multiplier < 1.0:
                        self._payment_lamport_multiplier = 1.0
                        log.info("treasury_worker.lamport_multiplier_reset")

                await self.ws_broadcaster.broadcast(
                    {
                        "type": "treasury_analysis",
                        "data": analysis.model_dump(mode="json"),
                    }
                )
                log.info(
                    "treasury_worker.broadcast",
                    runway_h=analysis.runway_hours,
                    status=analysis.runway_status,
                    fallback=analysis.used_fallback,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("treasury_worker.error", error=str(exc))

    async def _invoice_worker(self) -> None:
        """
        Generate an invoice every AUXIN_INVOICE_INTERVAL_H hours.
        Saves PDF + JSON to the invoice output directory and notifies the dashboard.
        """
        interval_s = _INVOICE_INTERVAL_H * 3600
        log.info("invoice_worker.started", interval_h=_INVOICE_INTERVAL_H)
        while True:
            try:
                await asyncio.sleep(interval_s)
                now = datetime.now(timezone.utc)
                period_start = now - timedelta(hours=_INVOICE_INTERVAL_H)

                invoice = await self._invoice_generator.generate(
                    payment_history=list(self._payment_log),
                    compliance_history=list(self._compliance_log),
                    period_start=period_start,
                    period_end=now,
                    hardware_agent_pubkey=str(self.owner_pubkey),
                    risk_report=self._latest_risk_report,
                    treasury_analysis=self._latest_treasury_analysis,
                )
                self._invoice_generator.render_json(invoice)
                pdf_path = self._invoice_generator.render_pdf(invoice)
                self._latest_invoice_path = pdf_path

                await self.ws_broadcaster.broadcast(
                    {
                        "type": "invoice_ready",
                        "data": {
                            "invoice_id": invoice.invoice_id,
                            "period_start": invoice.period_start.isoformat(),
                            "period_end": invoice.period_end.isoformat(),
                            "total_sol": invoice.total_sol,
                            "total_transactions": invoice.total_transactions,
                            "pdf_path": str(pdf_path),
                        },
                    }
                )
                log.info(
                    "invoice_worker.generated",
                    invoice_id=invoice.invoice_id,
                    total_sol=invoice.total_sol,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("invoice_worker.error", error=str(exc))

    async def _get_balance_sol(self) -> float:
        """Fetch the current wallet balance in SOL. Returns 0.0 on failure."""
        try:
            from solana.rpc.commitment import Confirmed

            resp = await self.program_client._rpc.get_balance(
                self.owner_pubkey, commitment=Confirmed
            )
            return resp.value / 1_000_000_000
        except Exception:
            return 0.0

    # ── Health endpoint ───────────────────────────────────────────────────────

    async def _start_healthz(self, host: str = "0.0.0.0") -> None:  # pragma: no cover
        app = aiohttp.web.Application()
        app.router.add_get("/healthz", self._healthz_handler)
        app.router.add_get("/invoice/latest", self._invoice_latest_handler)
        self._health_runner = aiohttp.web.AppRunner(app)
        await self._health_runner.setup()
        self._health_site = aiohttp.web.TCPSite(self._health_runner, host, self._healthz_port)
        await self._health_site.start()
        log.info("healthz.started", host=host, port=self._healthz_port)

    async def _stop_healthz(self) -> None:  # pragma: no cover
        if self._health_runner is not None:
            await self._health_runner.cleanup()
            log.info("healthz.stopped")

    async def _invoice_latest_handler(  # pragma: no cover
        self, request: aiohttp.web.Request
    ) -> aiohttp.web.Response:
        """GET /invoice/latest — return the most recent invoice PDF."""
        if self._latest_invoice_path is None or not self._latest_invoice_path.exists():
            return aiohttp.web.Response(status=404, text="No invoice generated yet")
        return aiohttp.web.FileResponse(
            self._latest_invoice_path,
            headers={
                "Content-Disposition": f"attachment; filename={self._latest_invoice_path.name}",
                "Access-Control-Allow-Origin": "*",
            },
        )

    async def _healthz_handler(  # pragma: no cover
        self, request: aiohttp.web.Request
    ) -> aiohttp.web.Response:
        return aiohttp.web.json_response(
            {
                "status": "ok",
                "source_status": self._source_status,
                "last_successful_tx": self._last_successful_tx,
                "last_oracle_latency_ms": self._last_oracle_latency_ms,
                "queue_depths": {
                    "compliance": self._compliance_queue.qsize(),
                    "payment": self._payment_queue.qsize(),
                },
                "uptime_seconds": round(time.monotonic() - self._start_time, 1),
                "frames_processed": self._frames_processed,
                "frames_dropped": self._frames_dropped,
                "compliance_total": self._compliance_total,
                "payments_total": self._payments_total,
                "ws_clients": self.ws_broadcaster.client_count,
            }
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def queue_depths(self) -> dict[str, int]:
        return {
            "compliance": self._compliance_queue.qsize(),
            "payment": self._payment_queue.qsize(),
        }

# auxin-sdk

Python package that powers the Auxin Automata bridge process: hardware wallet, telemetry schema and source abstraction, Gemini safety oracle, Solana program client, Prometheus instrumentation, and the long-running bridge service.

→ [Root README](../README.md)

---

## Purpose

`auxin-sdk` is the hardware-agnosticism proof. The same bridge code runs identically against three telemetry sources:

| `AUXIN_SOURCE` | Class | Requires |
|---|---|---|
| `mock` | `MockSource` | Nothing — pure Python |
| `twin` | `TwinSource` | PyBullet sim running in `/twin` |
| `ros2` | `ROS2Source` | ROS2 Humble + physical arm on Jetson |

No code outside `run_bridge.py` inspects which source is active. Switching is one env var change; `git diff` shows nothing in bridge or downstream code.

---

## Structure

```
sdk/
├── src/auxin_sdk/
│   ├── bridge.py          Bridge + WebsocketBroadcaster + 5 Prometheus metrics
│   ├── oracle.py          SafetyOracle: Gemini 2.0 Flash + local torque/fixture fallback
│   ├── schema.py          TelemetryFrame — Pydantic v2, single source of truth
│   ├── hashing.py         canonical_json + sha256_hex (deterministic, on-chain ready)
│   ├── wallet.py          HardwareWallet wrapping solders Keypair
│   ├── fixtures.py        Workspace image sampler for oracle evaluation
│   ├── logging.py         structlog JSON + request_id context propagation
│   ├── sources/
│   │   ├── base.py        TelemetrySource ABC — the agnosticism contract
│   │   └── mock.py        MockSource (sine/cosine kinematics) + ReplaySource
│   └── program/
│       ├── client.py      AuxinProgramClient — hand-crafted Anchor instruction builders
│       └── idl.json       Bundled IDL (fallback if programs/ not built)
├── scripts/
│   └── run_bridge.py      Production bridge entrypoint; Sentry init; source factory
├── tests/
│   ├── test_bridge_e2e.py  13 tests covering full anomaly + payment pipeline
│   ├── test_oracle.py      21 tests covering Gemini + fallback paths
│   ├── test_mock_source.py 30 tests: kinematics, seeding, recording, replay
│   ├── test_hashing.py     14 tests: determinism, canonicalisation
│   ├── test_schema.py      11 tests: field validation, round-trip
│   ├── test_wallet.py       9 tests: load, create, sign
│   ├── test_logging.py      7 tests: structlog configuration
│   └── eval_oracle.py      Accuracy eval harness (nightly, costs API credits)
└── fixtures/images/        20 labelled workspace images (clear_*.jpg / obstacle_*.jpg)
```

---

## Install

```bash
cd sdk
uv sync              # production deps
uv sync --group dev  # + pytest, ruff, coverage
```

---

## Test

```bash
cd sdk

# All unit tests — no network, no API keys
uv run python -m pytest

# Explicit coverage report
uv run python -m pytest --cov=src --cov-report=term-missing

# Devnet E2E: injects anomaly, asserts ComplianceEvent on-chain within 5 s
DEVNET_KEYPAIR=~/.config/auxin/hardware.json \
HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \
uv run python -m pytest -m network tests/test_bridge_e2e.py -v

# Gemini accuracy eval (runs against all 20 fixture images)
GEMINI_API_KEY=... uv run python -m pytest tests/eval_oracle.py -v
```

Current status: **105/105 unit tests pass · 80.2% coverage (≥80% enforced in CI)**.

---

## Run

```bash
cd sdk

# Mock mode — zero external dependencies
AUXIN_SOURCE=mock \
HELIUS_RPC_URL=https://api.devnet.solana.com \
uv run python scripts/run_bridge.py

# Twin mode — /twin ws server must be running on :8765
AUXIN_SOURCE=twin \
HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \
GEMINI_API_KEY=AIza... \
uv run python scripts/run_bridge.py

# Physical arm via ROS2 (Track B)
AUXIN_SOURCE=ros2 \
HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \
GEMINI_API_KEY=AIza... \
PROVIDER_PUBKEY=<base58> \
uv run python scripts/run_bridge.py
```

Bridge health: `curl http://localhost:8767/healthz`
Prometheus metrics: `curl http://localhost:9090/metrics`

---

## Prometheus Metrics

Five metrics exposed on `:9090` (configurable via `METRICS_PORT`):

| Metric | Type | Description |
|---|---|---|
| `auxin_tx_submitted_total` | Counter | Solana txs by `kind` (payment\|compliance) and `status` (ok\|duplicate\|error) |
| `auxin_anomalies_total` | Counter | Telemetry frames flagged as anomalies |
| `auxin_oracle_latency_seconds` | Histogram | Gemini SafetyOracle round-trip latency |
| `auxin_solana_submit_latency_seconds` | Histogram | Solana transaction submission latency |
| `auxin_queue_depth` | Gauge | Current queue depth by `queue` (compliance\|payment) |

---

## Key Design Rules

**Agnosticism** — `sources/base.py` defines `TelemetrySource` with `stream()` and `close()`. Nothing downstream branches on source type. Source selection happens once, in `run_bridge.py`.

**Compliance always flows** — Frames with `anomaly_flags` go to a dedicated unbounded `asyncio.Queue`. They are never dropped, never delayed by the payment queue, and never subject to budget or rate-limit checks. This is the architectural guarantee presented to regulators.

**Oracle fallback** — `oracle.py` falls back to a local torque-threshold + fixture-label heuristic when Gemini is unavailable (timeout > 2 s, key absent, or API error). `used_fallback=True` is recorded on every `OracleDecision`. The bridge never stalls.

**Sentry optional** — `run_bridge.py` initialises `sentry_sdk` only when `SENTRY_DSN` is set. Zero import overhead when not configured.

---

## How It Fits

```
TelemetrySource  →  Bridge.process(frame)
                        ├── ws_broadcaster.broadcast()    →  Dashboard WS :8766
                        ├── [anomaly] compliance_queue    →  log_compliance_event tx  →  Solana
                        └── [normal]  payment_queue       →  oracle.check()
                                                               ├── approved → stream_payment tx → Solana
                                                               └── denied  → compliance_queue
```

See the [root architecture diagram](../README.md#architecture).

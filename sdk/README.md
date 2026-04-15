# auxin-sdk

Python package that powers the Auxin Automata bridge process: hardware wallet, telemetry schema and source abstraction, Gemini safety oracle, Solana program client, and the long-running bridge service.

→ [Root README](../README.md)

---

## Purpose

`auxin-sdk` is the hardware-agnosticism proof. The same bridge code runs identically against three telemetry sources:

| `AUXIN_SOURCE` | Class | Requires |
|---|---|---|
| `mock` | `MockSource` | Nothing — pure Python |
| `twin` | `TwinSource` | PyBullet sim running in `/twin` |
| `ros2` | `ROS2Source` | ROS2 Humble + physical arm on Jetson |

No code outside the bridge entrypoint (`run_bridge.py`) inspects which source is active. Switching sources is a one-line env var change; `git diff` shows nothing in bridge or downstream code.

---

## Structure

```
sdk/
├── src/auxin_sdk/
│   ├── bridge.py          Bridge + WebsocketBroadcaster
│   ├── oracle.py          SafetyOracle: Gemini API with local fallback
│   ├── schema.py          TelemetryFrame — Pydantic v2, single source of truth
│   ├── hashing.py         canonical_json + sha256_hex (deterministic, on-chain ready)
│   ├── wallet.py          HardwareWallet wrapping solders Keypair
│   ├── fixtures.py        Workspace image sampler (oracle evaluation + fallback)
│   ├── logging.py         structlog JSON + request_id context propagation
│   ├── sources/
│   │   ├── base.py        TelemetrySource ABC — the agnosticism contract
│   │   └── mock.py        MockSource (sine/cosine kinematics) + ReplaySource
│   ├── program/
│   │   └── client.py      AuxinProgramClient — Anchor instruction wrappers
│   └── prompts/
│       └── safety_oracle_v1.txt  Versioned Gemini system prompt
├── scripts/
│   └── run_bridge.py      Production bridge entrypoint
├── tests/
│   ├── test_bridge_e2e.py Unit tests (always) + Devnet E2E (requires DEVNET_KEYPAIR)
│   ├── test_oracle.py
│   ├── test_mock_source.py
│   ├── test_hashing.py
│   ├── test_schema.py
│   ├── test_wallet.py
│   ├── test_logging.py
│   └── eval_oracle.py     Gemini accuracy eval harness (nightly, costs API credits)
└── fixtures/images/       20 labelled workspace images (clear_*.jpg / obstacle_*.jpg)
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

# All unit tests — no network, no API keys required
uv run python -m pytest

# With explicit coverage report
uv run python -m pytest --cov=src/auxin_sdk --cov-report=term-missing

# Devnet E2E: injects anomaly, asserts ComplianceEvent on-chain within 5 s
DEVNET_KEYPAIR=~/.config/auxin/hardware.json \
HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \
uv run python -m pytest -m network tests/test_bridge_e2e.py -v

# Nightly Gemini accuracy eval (runs against all 20 fixture images)
GEMINI_API_KEY=... uv run python -m pytest tests/eval_oracle.py -v
```

Current coverage: **80.2%** (≥80% required). 105/105 unit tests pass.

---

## Run

```bash
cd sdk

# Mock mode — no hardware, no Gemini key needed
AUXIN_SOURCE=mock \
HELIUS_RPC_URL=https://api.devnet.solana.com \
uv run python scripts/run_bridge.py

# Twin mode — /twin WebSocket server must be running on :8765 first
AUXIN_SOURCE=twin \
HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \
GEMINI_API_KEY=AIza... \
uv run python scripts/run_bridge.py

# Physical arm via ROS2 (Jetson, Track B)
AUXIN_SOURCE=ros2 \
HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \
GEMINI_API_KEY=AIza... \
PROVIDER_PUBKEY=<base58> \
uv run python scripts/run_bridge.py
```

Bridge status: `curl http://localhost:8767/healthz`

---

## Key Design Rules

**Agnosticism** — `sources/base.py` defines `TelemetrySource` with `stream()` and `close()`. No code in the bridge, oracle, or program client checks which concrete source is active. The source selection happens once at startup in `run_bridge.py`.

**Compliance always flows** — `bridge.py` routes frames with `anomaly_flags` to a dedicated unbounded `asyncio.Queue`. They are never dropped, never delayed by the payment queue, and never subject to budget checks. The payment queue (cap 50) governs only normal frames under backpressure.

**Oracle fallback** — `oracle.py` falls back to a local torque-threshold + fixture-label heuristic if the Gemini API is slow (>2 s timeout) or unavailable. `used_fallback=True` is recorded on every `OracleDecision`. The bridge never stalls on a Gemini outage.

---

## How It Fits

```
TelemetrySource  →  Bridge.process(frame)
                        ├── ws_broadcaster.broadcast()   →  Dashboard WS :8766
                        ├── [anomaly] compliance_queue   →  log_compliance_event tx  →  Solana
                        └── [normal]  payment_queue      →  oracle.check()
                                                              ├── approved → stream_payment tx  → Solana
                                                              └── denied  → compliance_queue
```

The bridge is the only process that touches both the telemetry stream and the Solana program. See the [root architecture diagram](../README.md#architecture).

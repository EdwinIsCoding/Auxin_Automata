# auxin-sdk

Python package powering the Auxin Automata bridge process. Hardware wallet, telemetry schema, source abstraction, Gemini safety oracle, and the long-running bridge service.

→ [Root README](../README.md)

---

## Purpose

`auxin-sdk` is the hardware-agnosticism proof. The same bridge code runs identically against three telemetry sources:

| `AUXIN_SOURCE` | Class | Requires |
|---|---|---|
| `mock` | `MockSource` | Nothing — pure Python |
| `twin` | `TwinSource` | PyBullet sim running in `/twin` |
| `ros2` | `ROS2Source` | ROS2 Humble + physical arm on Jetson |

Zero code branches on source type. Changing the source is a one-line env var edit.

---

## Structure

```
sdk/
├── src/auxin_sdk/
│   ├── bridge.py          Bridge + WebsocketBroadcaster (Phase 3)
│   ├── oracle.py          SafetyOracle: Gemini API with local fallback
│   ├── schema.py          TelemetryFrame — Pydantic v2, single source of truth
│   ├── hashing.py         canonical_json + sha256_hex (deterministic, on-chain)
│   ├── wallet.py          HardwareWallet wrapping solders Keypair
│   ├── fixtures.py        Workspace image sampler for oracle evaluation
│   ├── logging.py         structlog JSON + request_id context propagation
│   ├── sources/
│   │   ├── base.py        TelemetrySource ABC — the agnosticism contract
│   │   └── mock.py        MockSource + ReplaySource
│   └── program/
│       └── client.py      AuxinProgramClient — Anchor program calls
├── scripts/
│   └── run_bridge.py      Production bridge entrypoint
├── tests/                 pytest suite (≥80% coverage)
│   ├── test_bridge_e2e.py Unit tests + Devnet E2E (skipped without DEVNET_KEYPAIR)
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

# All unit tests (no network required)
uv run pytest -m "not network"

# With coverage
uv run pytest --cov=auxin_sdk --cov-report=term-missing

# Devnet E2E — injects anomaly, asserts ComplianceEvent on-chain within 5s
DEVNET_KEYPAIR=~/.config/auxin/hardware.json \
HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \
uv run pytest -m network tests/test_bridge_e2e.py -v
```

---

## Run

```bash
cd sdk

# Mock mode — no hardware, no Gemini key needed
AUXIN_SOURCE=mock \
HELIUS_RPC_URL=https://api.devnet.solana.com \
uv run python scripts/run_bridge.py

# Twin mode — requires /twin WebSocket server running on :8765
AUXIN_SOURCE=twin \
HELIUS_RPC_URL=... GEMINI_API_KEY=... \
uv run python scripts/run_bridge.py

# Full config — physical arm via ROS2
AUXIN_SOURCE=ros2 \
HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=... \
GEMINI_API_KEY=AIza... \
PROVIDER_PUBKEY=<base58> \
uv run python scripts/run_bridge.py
```

Healthcheck: `curl http://localhost:8767/healthz`

---

## Key Design Rules

**Agnosticism** — `sources/base.py` defines `TelemetrySource` with `stream()` and `close()`. No code outside the entrypoint ever checks which concrete source is active.

**Compliance always flows** — `bridge.py` routes frames with `anomaly_flags` to an unbounded `asyncio.Queue`. They are never dropped, never delayed by the payment queue, and never budget-checked. The payment queue (cap 50) governs only normal frames.

**Oracle fallback** — `oracle.py` falls back to a local torque-threshold heuristic if the Gemini API is slow (>2 s) or unavailable. The bridge never stalls on a network blip. `used_fallback=True` is recorded on the `OracleDecision`.

---

## How It Fits

```
TelemetrySource  →  Bridge.process(frame)
                        ├── ws_broadcaster.broadcast()   →  Dashboard WS :8766
                        ├── [anomaly] compliance_queue   →  log_compliance tx  →  Solana
                        └── [normal]  payment_queue      →  oracle.check()
                                                              ├── approved → stream_payment tx → Solana
                                                              └── denied  → compliance_queue
```

The bridge is the only process that touches both the telemetry stream and the Solana program. See the [root architecture diagram](../README.md#architecture) for the full picture.

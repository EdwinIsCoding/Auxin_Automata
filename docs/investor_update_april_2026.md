# Auxin Automata — Update

**April 15th 2026 · Colosseum Frontier Hackathon**
Edwin Redhead · Tara Kasayapanand

---

## What We Have Built

Auxin Automata is a middleware stack that makes physical hardware financially and legally autonomous. A robotic arm, or any edge compute device, can hold its own Solana wallet, pay for AI inference as it runs, and hash its safety telemetry to an immutable on-chain log, all without a human signing transactions.

Over the past five weeks we built the complete vertical slice: a Rust Solana program live on Devnet, a Python SDK running against three hardware backends, a PyBullet digital twin, a Next.js observability dashboard, and a Docker-compose demo stack that reproduces the entire thing from a `git clone` in under 60 seconds.

The core thesis has not changed. What is new is that it works, end-to-end, today.

---

## The Three Pillars — Implemented

### 1. Autonomous Hardware Wallets

The hardware device holds a `solders` Keypair stored in a JSON file on the edge compute node. This keypair signs Solana transactions directly — the owner account funds the initial compute budget via `initialize_agent` and then steps out of the signing path permanently. Every subsequent payment and every compliance log is signed by the hardware itself.

This is not a custodial arrangement. The hardware is the signer. If the network is down, the hardware waits and retries. If the owner disappears, the hardware continues operating on its pre-funded budget.

**On-chain:** `HardwareAgent` PDA seeded by `[b"agent", owner_pubkey]`, storing the hardware public key, compute budget lamports, lamports spent, whitelisted provider set (max 8), and a rolling rate-limit window.

### 2. M2M Micropayments

When the Gemini Safety Oracle approves an action, the bridge sends a `stream_compute_payment` instruction signed by the hardware wallet. Lamports move from the `HardwareAgent` PDA to the `ComputeProvider` PDA in a single atomic transfer. The program enforces a 0.001 SOL cap per transaction and a 100-transaction/60-slot rolling window.

The payment pipeline runs through an async queue in the bridge process. Under backpressure (when Solana is slow or the oracle is slow), new frames are dropped from this queue. This is intentional: micropayments are a best-effort economic signal, not a safety primitive.

**On-chain:** `stream_compute_payment` instruction → `ComputePaymentEvent` (agent, provider, lamports, cumulative total, slot).

### 3. Immutable Compliance Logging

When the Safety Oracle detects an anomaly — either from the hardware's own `anomaly_flags` field (e.g., a PyBullet collision detection hit) or from the oracle denying a payment request — the bridge writes a `ComplianceLog` PDA to Solana. The log contains the SHA-256 hash of the complete raw telemetry frame at the moment of the event.

This queue is unbounded and is never dropped. The code contract is enforced at the `asyncio.Queue` level: the payment queue has `maxsize=50` and drops frames under backpressure; the compliance queue has no maxsize. The bridge drains the compliance queue for up to 30 seconds on shutdown before exiting.

**On-chain:** `log_compliance_event` instruction → `ComplianceLog` PDA (hash, severity 0–3, reason_code, slot, timestamp). No budget checks. No rate limits. No exceptions.

---

## The Hardware-Agnosticism Proof

The central engineering claim is that our compliance architecture is not tied to any specific hardware. We prove this structurally.

`TelemetrySource` is an abstract base class with two methods: `stream()` returns an async iterator of `TelemetryFrame` objects, and `close()` shuts it down. There are three concrete implementations:

- **`MockSource`** — pure Python, sine/cosine kinematics, seeded RNG, no external dependencies
- **`TwinSource`** — PyBullet Franka Panda simulation, collision detection, 240 Hz internal sim rate
- **`ROS2Source`** — subscribes to `/joint_states` on the Jetson, throttled to 2 Hz

The bridge, oracle, and Solana client import none of these directly. They receive a `TelemetrySource` instance from `run_bridge.py` and call `source.stream()`. There is no `isinstance` check, no `if source == "ros2"` branch, and no conditional import anywhere in the downstream code. Switching hardware backends requires changing one environment variable: `AUXIN_SOURCE=mock|twin|ros2`.

This is not a claim we make in documentation. It is a claim enforceable by reading `bridge.py`: grep for `"ros2"`, `"twin"`, `"mock"` — you will find zero results outside the entrypoint.

---

## What Is Running on Devnet

Program ID: `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm`

Deployed 2026-04-14. The IDL is on-chain. All four instructions are callable. We have run the full E2E test: the bridge starts in twin mode, the digital twin forces a collision at frame 30, the Gemini Oracle logs the denial, a `ComplianceLog` PDA is created on Devnet, and the compliance hash appears in Solana Explorer within ~2 seconds of the collision.

The dashboard reads these events live via `connection.onLogs`. The binary Borsh event payloads are decoded client-side using a hand-written `BorshReader` class (we do not bundle `@coral-xyz/anchor` in the browser — it imports Node.js file system modules).

---

## The Safety Architecture

The physical arm safety guarantee is provided by a ROS2 node called `safety_watchdog_node` running as an independent systemd service on the Jetson. It subscribes to `/joint_states`, monitors effort values, and calls `/emergency_stop` if any joint torque exceeds 80 N·m for 3 consecutive frames.

This node does not import `auxin-sdk`. It does not make any HTTP or WebSocket calls. It does not know Solana exists. Its dependency list is: `rclpy`, `sensor_msgs`, `std_msgs`, `std_srvs`. Nothing else.

This means: if the bridge crashes, if the network goes down, if Solana is unavailable, if the oracle hangs — the watchdog still halts the arm. The safety guarantee does not sit on top of our software stack; it sits below it, running independently, on a process the software stack cannot reach.

This is the argument we make to regulators and to industrial customers. Hardware safety must be structurally independent of software infrastructure. We have built it that way.

---

## Observability and Production Readiness

The bridge process exposes five Prometheus metrics on `:9090`:

| Metric | What it measures |
|---|---|
| `auxin_tx_submitted_total{kind, status}` | Solana transaction volume by type and outcome |
| `auxin_anomalies_total` | Anomaly frame rate over time |
| `auxin_oracle_latency_seconds` | Gemini API round-trip latency distribution |
| `auxin_solana_submit_latency_seconds` | Solana confirmation latency distribution |
| `auxin_queue_depth{queue}` | Real-time compliance vs. payment queue depth |

A Grafana dashboard auto-provisions on `make demo` with four panels showing these metrics. Sentry error tracking is optional in both the Python bridge and the Next.js dashboard, activated by setting `SENTRY_DSN` / `NEXT_PUBLIC_SENTRY_DSN`.

The `scripts/healthcheck.sh` script hits `/healthz` on the bridge and validates `source_status == "streaming"`. This is what the Docker healthcheck uses to gate the dashboard container startup.

---

## Software Quality

| Area | Metric |
|---|---|
| SDK unit tests | 105 passing, 0 failing |
| SDK test coverage | 80.2% (≥80% enforced in CI) |
| Twin tests | 16 passing, 0 failing |
| Anchor TypeScript tests | 23 passing, 1 pending (rate-limit slot batching) |
| Dashboard ESLint | 0 warnings, 0 errors |
| Dashboard TypeScript | strict mode, 0 type errors |
| Production build | 553 kB first load JS (no `@coral-xyz/anchor` in browser bundle) |
| `ruff check` | All checks passed (sdk + twin) |
| `ruff format` | All files formatted |
| `cargo clippy` | Clean (Anchor macro suppressions documented) |

CI runs on every push to `main` via GitHub Actions. Three jobs: Python lint/test (sdk + twin), Anchor build/clippy/test, dashboard lint/build.

---

## The Demo Stack

`make demo` starts five containers in order:

1. **twin** — PyBullet ws server serving base64-encoded JPEG frames on `:8765`
2. **bridge** — Python bridge in `AUXIN_SOURCE=twin` mode; connects to twin, starts processing frames, metrics on `:9090`, healthz on `:8767`
3. **dashboard** — Next.js production build connecting to bridge on `:8766` and Solana Devnet
4. **prometheus** — scrapes bridge every 5 seconds
5. **grafana** — auto-provisions Prometheus datasource and Auxin dashboard

Total services: 5. Cold start: ~45–55 seconds on a 2021 M1 MacBook Pro. Keypairs are mounted read-only from the host; the bridge signs real Devnet transactions.

---

## Track A vs Track B

**Track A (current):** PyBullet digital twin running on the developer machine. Everything except the physical arm is fully implemented. The twin produces `TelemetryFrame` objects identical in schema to what the ROS2 nodes produce. The dashboard, bridge, oracle, and Solana program are all exercised end-to-end against the twin.

**Track B (hardware):** NVIDIA Jetson Orin Nano + myCobot 280 arm. Gated on the Superteam Ireland hardware grant. The ROS2 nodes (`telemetry_bridge_node`, `safety_watchdog_node`, `ROS2Source`) are coded, tested offline, and ready to deploy when hardware ships. Switching from Track A to Track B is: change `AUXIN_SOURCE=twin` to `AUXIN_SOURCE=ros2`. Zero code changes in the bridge, oracle, or dashboard.

---

## Business Model

**Near term (6 months):** SDK licensing to DePIN operators and robotics companies integrating autonomous payment rails into their hardware fleet. Per-device monthly fee, tiered by transaction volume.

**Medium term (18 months):** Compliance-as-a-Service for regulated industries (surgical robotics, autonomous vehicles, industrial automation). On-chain compliance logs are an audit trail that operators can present to regulators and insurers. We charge for the infrastructure, the oracle calls, and optionally for managed key custody.

**Long term:** Become the financial and compliance layer for the agentic machine economy. Every autonomous device — drone, robot arm, autonomous vehicle, DePIN sensor node — needs to pay for compute, log anomalies, and prove its operational history. We are building the rail.

The three pillars are not independent features. They are a bundle: you cannot have compliant autonomous payments without the wallet; you cannot have the wallet without the compliance infrastructure; regulators require the compliance log before they allow the wallet. The bundle is the moat.

---

## Why Solana

Sub-second finality at sub-cent fee costs is not a preference — it is a requirement for machine-to-machine micropayments. A robot arm making 10 safety decisions per second cannot wait 15 seconds for a transaction to confirm. A compliance log that costs $0.10 per entry is not viable at industrial scale.

Solana's localised fee markets mean that a fleet of 1,000 devices can operate simultaneously without congesting each other. The hardware wallet architecture maps cleanly onto Solana's account model: each device is a PDA with its own lamport balance and its own signing key.

We evaluated Ethereum L2s. The developer tooling is better (Foundry, Hardhat). The ecosystem is larger. But for M2M micropayments at the frequency we require, Solana is the only production-viable chain today.

---

## The Ask

We are pursuing two parallel paths:

1. **Superteam Ireland hardware grant** — to fund Track B (Jetson Orin Nano + physical arm). This converts the demo from a simulation to a live physical demonstration. We expect to hear back within 6 weeks.

2. **Seed round** — we are open to conversations with investors who want early access to the M2M payment and compliance infrastructure layer for the agentic economy. The Colosseum Frontier submission is the technical due diligence package. The code is open source and auditable.

The digital twin demo is not a prototype. It is a production-quality implementation running real transactions on Solana Devnet. The gap between Track A and Track B is one hardware procurement and one environment variable.

---

## Technical Appendix: Key Files

| File | What it proves |
|---|---|
| `sdk/src/auxin_sdk/sources/base.py` | The agnosticism contract — `TelemetrySource` ABC |
| `sdk/src/auxin_sdk/bridge.py` | No source-type branches; compliance queue is unbounded |
| `programs/programs/agentic_hardware_bridge/src/instructions/log_compliance_event.rs` | No rate-limit or budget check on compliance writes |
| `edge/auxin_edge/safety_watchdog_node.py` | No `auxin_sdk` import; no network calls |
| `sdk/tests/test_bridge_e2e.py` | End-to-end anomaly → compliance hash → Solana |
| `dashboard/lib/anchor.ts` | Browser-safe Borsh decoder without Node.js dependencies |
| `docker-compose.demo.yml` | Full reproducible stack in one file |

---

*Edwin Redhead — edwin@auxinautomata.io — GitHub @EdwinIsCoding*
*Tara Kasayapanand — tara@auxinautomata.io — GitHub @tara-kas*
*Superteam Ireland · Colosseum Frontier Hackathon · April 2026*

# Auxin Automata — CLAUDE.md

## Project Identity

5-week Colosseum Frontier Hackathon. Team: Edwin Redhead (GitHub: EdwinIsCoding) + Tara Kasayapanand.
Spec files at repo root (do not delete):
- `auxin_automata_overview.tex` — product vision, architecture pillars, MVP scope
- `auxin_automata_phases.tex` — phase-by-phase engineering checklist (Phases 0–4)
- `auxin_automata_prompts.tex` — master prompts to paste per phase (Prompts Playbook)

Build proceeds phase-by-phase. Each phase prompt comes from `auxin_automata_prompts.tex`.

## Stack Pins (do not substitute)

| Tool | Version |
|---|---|
| Python | 3.11 |
| Package manager (Python) | `uv` (not pip, not poetry) |
| Node | 20 |
| Package manager (Node) | `pnpm` |
| Rust | stable |
| Solana CLI | 1.18+ |
| Anchor | 0.30+ |
| ROS2 | Humble |
| Next.js | 14 (app router) |

## Workspace Map

| Path | Purpose |
|---|---|
| `/sdk` | Python `auxin-sdk` package: wallet, schema, telemetry sources ABC, Gemini oracle, bridge service |
| `/programs` | Anchor/Rust workspace: `agentic_hardware_bridge` Solana program |
| `/edge` | ROS2 Python nodes for Jetson: `telemetry_bridge_node` + `safety_watchdog_node` |
| `/dashboard` | Next.js 14 dashboard: TelemetryCard, PaymentTicker, ComplianceTable, TwinViewport |
| `/twin` | PyBullet digital twin: simulation, `TwinSource`, websocket frame server, MP4 renderer |
| `/docs` | Architecture docs and design documents |
| `/scripts` | Deploy, healthcheck, and keypair bootstrap scripts |

## The Agnosticism Contract (critical — never break)

`TelemetrySource` ABC lives at: `/sdk/src/auxin_sdk/sources/base.py`

- Methods: `async def stream() -> AsyncIterator[TelemetryFrame]` and `async def close()`
- Concrete implementations: `MockSource`, `TwinSource`, `ROS2Source`
- Selected exclusively by `AUXIN_SOURCE=mock|twin|ros2` env var
- **Zero conditional branches on source type in the bridge or any downstream code.**
- Changing the telemetry source = one env var change, zero code changes.
- This is the hardware-agnosticism proof for hackathon judges.

## Compliance Event Rule (never violate)

Compliance events are **NEVER** rate-limited, budget-blocked, or dropped under backpressure.
They have a separate unbounded queue in the bridge process.
Every other event type may be throttled or dropped; compliance events cannot.

## Watchdog Independence Rule (never violate)

`/edge/auxin_edge/safety_watchdog_node.py` runs as a separate ROS2 process under its own systemd unit.
- **Must NOT import `auxin-sdk`**
- **Must NOT make any network calls**
- Purely local ROS2: subscribes `/joint_states`, calls `/emergency_stop` service
- Independence from the rest of the software stack IS the safety guarantee.
- If the bridge crashes, network dies, or Solana is down — watchdog still halts the arm.

## Digital Twin Fallback Strategy

`/twin` (PyBullet Franka Panda simulation) is the insurance policy if the physical arm fails.
Track B (Jetson + physical arm) is gated on Superteam grant — hardware may not arrive.
`TwinSource` must be byte-identical in interface to `ROS2Source`.
Twin must be production-ready (Phase 1C complete) **before** Track B begins.
A twin-mode demo still proves all three architectural pillars end-to-end.

## Port Map

| Port | Service |
|---|---|
| 8765 | Twin websocket server (PyBullet JPEG frames, base64-encoded) |
| 8766 | Bridge websocket broadcaster (live telemetry → dashboard) |
| 8767 | Bridge `/healthz` JSON status endpoint |
| 9090 | Prometheus metrics |

## CODEOWNERS Split

- Edwin primary: `/sdk`, `/programs`
- Tara primary: `/dashboard`, `/twin`
- Joint: `/edge`, root files

## Open Questions (resolve before writing code in the relevant phase)

1. **anchorpy + Anchor 0.30 compatibility** — verify before Phase 2A Python client generation (2A.11). May need to hand-write the Python client from the IDL JSON if anchorpy doesn't support 0.30.
2. **Nightly eval CI mechanism** — Phase 1D says "CI fails on regression" but the eval runs nightly only (costs API credits). Decide: does the nightly job gate merges, or is it advisory-only?
3. ~~Tara's GitHub username~~ — resolved: @tara-kas

# Auxin Automata

> The Agentic Infrastructure API for Autonomous Hardware

Bridging high-frequency telemetry, Solana M2M micropayments, and immutable compliance.

_Full architecture diagram, quickstart, and deployed addresses will be added in Phase 4._

---

## What It Does

Auxin Automata gives physical hardware — robotic arms, drones, industrial machines — its own
on-chain Solana wallet. The hardware autonomously streams micropayments for AI inference and
compute, while hashing kinematic safety telemetry to Solana as a tamper-proof compliance log.

**MVP:** A ROS2 robotic arm on an NVIDIA Jetson Orin Nano, paying Google Gemini for vision
inference and logging torque-anomaly events to Solana Devnet, visualised on a live Next.js
dashboard.

---

## Workspaces

| Path | Purpose |
|---|---|
| `/sdk` | Python `auxin-sdk`: wallet, telemetry schema, source abstraction, Gemini oracle, bridge service |
| `/programs` | Anchor/Rust: `agentic_hardware_bridge` Solana program |
| `/edge` | ROS2 Python nodes for Jetson: telemetry bridge + independent safety watchdog |
| `/dashboard` | Next.js 14 dashboard: digital twin viewport, M2M payment ticker, compliance log |
| `/twin` | PyBullet digital twin: simulation, `TwinSource`, websocket frame server |
| `/docs` | Architecture docs and design documents |
| `/scripts` | Deploy, healthcheck, and bootstrap scripts |

---

## Quick Start

```bash
# Requires Docker
make demo
# Open http://localhost:3000
```

_Full quickstart with environment variable reference in Phase 4 documentation._

---

## Team

**Edwin Redhead** & **Tara Kasayapanand** — Colosseum Frontier Hackathon 2026

---

## License

Apache 2.0 — see [LICENSE](./LICENSE)

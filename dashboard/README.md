# Dashboard

Next.js 14 dashboard. Real-time visualisation of the robot's digital twin, live M2M payment stream, and immutable compliance log.

→ [Root README](../README.md)

---

## Purpose

The dashboard is the visual proof judges see. It consumes data from two independent sources simultaneously:

- **Bridge WebSocket (:8766)** — off-chain telemetry at 10 Hz (too high-frequency for Solana), fed by the Python bridge process
- **Solana RPC (`onLogs`)** — on-chain `ComputePaymentEvent` and `ComplianceEvent` from the Anchor program, as they confirm

Both connections auto-reconnect. Every panel handles loading, empty, and error states — no white screens during the demo.

---

## Stack

- Next.js 14, App Router, TypeScript strict
- Tailwind CSS with Mechafloral design tokens (dark slate / Solana green / deep teal)
- shadcn/ui components
- Recharts for joint angle and torque sparklines
- react-three-fiber for the URDF twin viewport
- Zustand for state management
- `@solana/web3.js` for on-chain event subscriptions

---

## Structure

```
dashboard/
├── app/
│   ├── layout.tsx              Root layout: dark mode locked, Inter font, Sentry init
│   └── page.tsx                Three-column grid: telemetry | payments + compliance | twin
├── components/
│   ├── Header.tsx              Agent pubkey, WS connection status, pulsing live indicator
│   ├── TelemetryCard.tsx       Joint angle + torque sparklines; border shifts red on anomaly
│   ├── PaymentTicker.tsx       Scrolling ComputePaymentEvent list with Explorer links
│   ├── ComplianceTable.tsx     Sortable ComplianceEvent table: severity badges, hash copy-button
│   ├── TwinViewport.tsx        react-three-fiber canvas fed by WS :8765 or bridge joint states
│   └── SentryProvider.tsx      Client-side Sentry boundary
└── lib/
    ├── store.ts                Zustand store: telemetry, payments, complianceLogs arrays
    ├── solana.ts               Connection factory reading env vars; PROGRAM_ID export
    ├── anchor.ts               Anchor Program instance (read-only provider + IDL)
    ├── useProgramEvents.ts     program.addEventListener wrapper: reconnect, dedup, cleanup
    ├── useBridgeSocket.ts      Bridge WS hook: reconnect with exponential backoff
    ├── mockData.ts             Seeded mock data for development without a running bridge
    └── idl/
        └── agentic_hardware_bridge.json  IDL copied from /programs/target/idl/
```

---

## Install

```bash
cd dashboard
pnpm install
```

---

## Develop, Lint, Build

```bash
cd dashboard

# Development server — mock data, no env vars required
pnpm dev
# http://localhost:3000

# ESLint check (0 warnings or errors)
pnpm lint

# Production build check — catches TypeScript errors and missing pages
pnpm build
```

No ESLint errors or warnings. Production build generates all 4 static routes cleanly.

---

## Run with Live Data

```bash
cp .env.example .env.local
# Edit .env.local: set NEXT_PUBLIC_HELIUS_RPC_URL (wss://) and NEXT_PUBLIC_PROGRAM_ID

pnpm dev   # or: pnpm build && pnpm start
```

The dashboard degrades gracefully if the bridge WebSocket or Solana RPC is unreachable — it falls back to the last known state and shows a disconnected indicator in the header.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_HELIUS_RPC_URL` | yes (live) | — | Helius / QuickNode RPC — must be `wss://` for `onLogs` subscriptions |
| `NEXT_PUBLIC_PROGRAM_ID` | yes (live) | — | Deployed program address |
| `NEXT_PUBLIC_AGENT_PUBKEY` | no | — | Agent pubkey displayed in Header |
| `NEXT_PUBLIC_BRIDGE_WS_URL` | no | `ws://localhost:8766` | Bridge telemetry WebSocket |
| `NEXT_PUBLIC_TWIN_WS_URL` | no | `ws://localhost:8765` | Twin JPEG frame WebSocket |
| `NEXT_PUBLIC_SENTRY_DSN` | no | — | Sentry error tracking |

---

## Design Tokens (Mechafloral)

| Token | Value | Use |
|---|---|---|
| Background | `#0a0e1a` | Root background |
| Surface | `#131826` | Card backgrounds |
| Border | `#1f2937` | Card and table borders |
| Accent teal | `#14b8a6` | Primary interactive accent |
| Accent Solana | `#14F195` | Payment events, live indicators |
| Text primary | `#f1f5f9` | Body text |
| Text muted | `#94a3b8` | Subtitles, metadata |
| Danger | `#ef4444` | Anomaly flags, critical compliance events |

---

## How It Fits

```
Bridge WS :8766  →  TelemetryCard  (live joint angles + torques, 10 Hz)
                 →  TwinViewport   (joint state feed when AUXIN_SOURCE≠twin)

Twin WS :8765    →  TwinViewport   (JPEG frames when AUXIN_SOURCE=twin)

Solana onLogs    →  PaymentTicker  (ComputePaymentEvent — one row per tx)
                 →  ComplianceTable (ComplianceEvent — one row per anomaly)
```

The dashboard is read-only. It never signs transactions and never imports private keys. See the [root architecture diagram](../README.md#architecture).

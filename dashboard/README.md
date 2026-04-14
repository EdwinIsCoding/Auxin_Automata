# Dashboard

Next.js 14 dashboard. Real-time visualisation of the robot's digital twin, live M2M payment stream, and immutable compliance log.

→ [Root README](../README.md)

---

## Purpose

The dashboard is the visual proof of concept judges see. It consumes data from two sources simultaneously:

- **Bridge WebSocket (:8766)** — off-chain telemetry at 10 Hz (too fast for Solana), fed by the Python bridge process
- **Solana RPC (onLogs)** — on-chain `ComputePaymentEvent` and `ComplianceEvent` from the Anchor program, as they land

Both connections are live and reconnecting. The dashboard never shows a white screen.

---

## Stack

- Next.js 14, App Router, TypeScript strict
- Tailwind CSS with Mechafloral design tokens (dark slate / Solana green / deep teal)
- shadcn/ui components
- Recharts for sparklines
- react-three-fiber for the URDF twin viewport
- Zustand for state management
- `@solana/web3.js` for on-chain event subscriptions

---

## Structure

```
dashboard/
├── app/
│   ├── layout.tsx              Root layout, dark mode locked, Inter font
│   └── page.tsx                Three-column grid: telemetry | payments + compliance | twin
├── components/
│   ├── Header.tsx              Agent pubkey, connection status, pulsing live indicator
│   ├── TelemetryCard.tsx       Joint angle + torque sparklines; red border on anomaly
│   ├── PaymentTicker.tsx       Scrolling ComputePaymentEvent list with Explorer links
│   ├── ComplianceTable.tsx     Sortable ComplianceEvent table, severity badges, hash copy
│   └── TwinViewport.tsx        react-three-fiber canvas, URDF, fed by WS :8765 or bridge
├── hooks/
│   └── useProgramEvents.ts     program.addEventListener wrapper; reconnect + dedup
├── lib/
│   ├── store.ts                Zustand store for telemetry, payments, compliance arrays
│   ├── solana.ts               Connection factory from env vars
│   └── anchor.ts               Anchor Program instance with read-only provider
└── .env.example                All required variables documented
```

---

## Install

```bash
cd dashboard
pnpm install
```

---

## Test

```bash
cd dashboard
pnpm test        # vitest unit tests (if present)
pnpm lint        # ESLint + TypeScript
pnpm build       # production build check
```

---

## Run

```bash
cd dashboard

# Development — mock data, no env vars required
pnpm dev
# Open http://localhost:3000

# With live bridge + Solana
cp .env.example .env.local
# Edit .env.local: set NEXT_PUBLIC_HELIUS_RPC_URL and NEXT_PUBLIC_PROGRAM_ID
pnpm dev
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_HELIUS_RPC_URL` | yes (live) | — | Helius/QuickNode RPC (`wss://` for event subscriptions) |
| `NEXT_PUBLIC_PROGRAM_ID` | yes (live) | — | Deployed program ID |
| `NEXT_PUBLIC_BRIDGE_WS_URL` | no | `ws://localhost:8766` | Bridge telemetry WebSocket |
| `NEXT_PUBLIC_TWIN_WS_URL` | no | `ws://localhost:8765` | Twin JPEG frame WebSocket |
| `NEXT_PUBLIC_SENTRY_DSN` | no | — | Sentry error tracking (Phase 4) |

---

## Design Tokens (Mechafloral)

| Token | Value | Use |
|---|---|---|
| Background | `#0a0e1a` | Root background |
| Surface | `#131826` | Card backgrounds |
| Border | `#1f2937` | Card and table borders |
| Accent teal | `#14b8a6` | Primary accent |
| Accent Solana | `#14F195` | Payment events, live indicators |
| Text primary | `#f1f5f9` | Body text |
| Text muted | `#94a3b8` | Subtitles, metadata |
| Danger | `#ef4444` | Anomaly flags, critical compliance |

---

## How It Fits

```
Bridge WS :8766 → TelemetryCard (live joint angles + torques)
                → TwinViewport (joint state feed when AUXIN_SOURCE≠twin)

Twin WS :8765   → TwinViewport (JPEG frames when AUXIN_SOURCE=twin)

Solana onLogs   → PaymentTicker (ComputePaymentEvent)
                → ComplianceTable (ComplianceEvent)
```

The dashboard is read-only — it never signs transactions. It does not import private keys. See the [root architecture diagram](../README.md#architecture).

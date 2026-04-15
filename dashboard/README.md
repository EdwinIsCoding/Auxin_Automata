# Dashboard

Next.js 14 dashboard. Real-time visualisation of the robot's digital twin, live M2M payment stream, and immutable compliance log.

→ [Root README](../README.md)

---

## Purpose

The dashboard is the visual proof judges see. It consumes data from two independent sources simultaneously:

- **Bridge WebSocket (:8766)** — off-chain telemetry at 10 Hz, fed by the Python bridge process
- **Solana RPC (`onLogs`)** — on-chain `ComputePaymentEvent` and `ComplianceEvent` from the Anchor program, decoded from binary Borsh logs without `@coral-xyz/anchor` (browser-safe custom BorshReader)

Both connections auto-reconnect with exponential backoff. Every panel handles loading, empty, and disconnected states — no white screens during the demo.

---

## Stack

- Next.js 14, App Router, TypeScript strict mode
- Tailwind CSS with Mechafloral design tokens (dark slate / Solana green / deep teal)
- shadcn/ui base components
- Recharts for joint angle and torque sparklines
- react-three-fiber for the 3D arm fallback viewport
- Zustand for global state
- `@solana/web3.js` for on-chain event subscriptions
- `framer-motion` for animated WS status transitions
- `@sentry/react` (optional, only loaded when `NEXT_PUBLIC_SENTRY_DSN` is set)

---

## Structure

```
dashboard/
├── app/
│   ├── layout.tsx              Root layout: dark mode, Inter font, SentryProvider
│   └── page.tsx                Three-column grid: telemetry | payments + compliance | twin
├── components/
│   ├── Header.tsx              Agent pubkey, animated WS status (live/connecting/disconnected)
│   ├── TelemetryCard.tsx       Joint angle + torque sparklines; red glow on anomaly
│   ├── PaymentTicker.tsx       Live ComputePaymentEvent scroll with Explorer links
│   ├── ComplianceTable.tsx     Sortable ComplianceEvent table: severity badges, hash copy-button
│   ├── TwinViewport.tsx        JPEG stream overlay (twin mode) or react-three-fiber 3D fallback
│   └── SentryProvider.tsx      Client boundary — lazy-loads @sentry/react when DSN is set
└── lib/
    ├── store.ts                Zustand: telemetry, payments, complianceLogs, wsStatus
    ├── solana.ts               Connection + PublicKey factory from env vars
    ├── anchor.ts               Custom BorshReader — decodes Anchor events without Node modules
    ├── useProgramEvents.ts     onLogs subscription: binary decode → text fallback → dedup
    ├── useBridgeSocket.ts      Bridge WS hook: exponential backoff reconnect, wsStatus updates
    ├── mockData.ts             Seeded dev data for working without a running bridge
    └── idl/
        └── agentic_hardware_bridge.json   IDL copy for browser-side discriminator lookup
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

# Development server — mock data works without env vars
pnpm dev                     # http://localhost:3000

# ESLint (0 warnings or errors)
pnpm lint

# Production build — TypeScript strict + static analysis
pnpm build
```

Status: **0 ESLint warnings · clean TypeScript build · 553 kB first load JS**.

---

## Run with Live Data

```bash
cp .env.example .env.local
# Set NEXT_PUBLIC_HELIUS_RPC_URL (must be wss://) and NEXT_PUBLIC_PROGRAM_ID

pnpm dev    # or: pnpm build && pnpm start
```

The dashboard degrades gracefully if the bridge WebSocket or Solana RPC is unreachable — it shows a disconnected indicator in the Header and retains the last known state.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_HELIUS_RPC_URL` | yes (live) | — | Must be `wss://` for `onLogs` subscriptions |
| `NEXT_PUBLIC_PROGRAM_ID` | yes (live) | — | Deployed program address |
| `NEXT_PUBLIC_AGENT_PUBKEY` | no | — | Agent pubkey displayed in Header |
| `NEXT_PUBLIC_BRIDGE_WS_URL` | no | `ws://localhost:8766` | Bridge telemetry WebSocket |
| `NEXT_PUBLIC_TWIN_WS_URL` | no | `ws://localhost:8765` | Twin JPEG frame WebSocket |
| `NEXT_PUBLIC_SENTRY_DSN` | no | — | Client-side Sentry (optional; zero bundle cost when unset) |

---

## Design Tokens (Mechafloral)

| Token | Value | Used for |
|---|---|---|
| Background | `#0a0e1a` | Root background |
| Surface | `#131826` | Card backgrounds |
| Accent teal | `#14b8a6` | TwinViewport, TelemetryCard headers |
| Accent Solana green | `#14F195` | Live indicators, payment events |
| Accent purple | `#A855F7` | ComplianceTable, Header |
| Text primary | `#f1f5f9` | Body copy |
| Text muted | `#94a3b8` | Subtitles, timestamps |
| Danger | `#ef4444` | Anomaly flags, CRIT severity rows, red glow |

---

## On-Chain Event Decoding

The dashboard does not import `@coral-xyz/anchor` (it uses Node.js file system APIs incompatible with the browser bundle). Instead, `lib/anchor.ts` contains a hand-written `BorshReader` class that:

1. Decodes the base64 payload from `"Program data: ..."` log lines
2. Checks the first 8 bytes against hardcoded discriminators (`ComplianceEvent`, `ComputePaymentEvent`)
3. Reads fields in Borsh order: `pubkey` (32 bytes), `u64` (8 LE bytes), `string` (4-byte length prefix + UTF-8), etc.

This approach has zero external dependencies and works identically in any browser or edge runtime.

---

## How It Fits

```
Bridge WS :8766  →  useBridgeSocket  →  store.telemetry    →  TelemetryCard
                                     →  store.wsStatus     →  Header
Twin WS :8765    →  TwinViewport (JPEG overlay when live)
                    TwinViewport (3D canvas fallback when disconnected)
Solana onLogs    →  useProgramEvents →  store.payments     →  PaymentTicker
                                     →  store.compliance   →  ComplianceTable
```

See the [root architecture diagram](../README.md#architecture).

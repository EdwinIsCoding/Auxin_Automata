# agentic_hardware_bridge

Anchor 0.30+ Solana program. Handles autonomous M2M micropayments and immutable compliance logging for hardware agents.

→ [Root README](../README.md) · [PDA Design](./DESIGN.md) · [Security Checklist](./SECURITY.md)

---

## Deployed

| Cluster | Program ID | Explorer |
|---|---|---|
| Devnet | `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm` | [View](https://explorer.solana.com/address/7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm?cluster=devnet) |
| Localnet | `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm` | — |

---

## Program Accounts

### HardwareAgent PDA
Seeds: `[b"agent", owner_pubkey]`

Represents one autonomous hardware device. Stores compute budget, lamports spent, whitelisted provider list (max 8), and rate-limit window state.

### ComputeProvider PDA
Seeds: `[b"provider", provider_pubkey]`

Tracks cumulative lamports received by a provider across all agents. Initialised lazily on first payment.

### ComplianceLog PDA
Seeds: `[b"log", agent_pda, slot.to_le_bytes()]`

Immutable record of one compliance event. Stores a 64-char hex hash of the raw telemetry frame, severity (0–3), and reason code. **Never rate-limited or budget-blocked.**

---

## Instructions

| Instruction | Signer | Description |
|---|---|---|
| `initialize_agent` | owner | Creates `HardwareAgent` PDA, funds with compute budget |
| `stream_compute_payment` | hardware_pubkey | Transfers lamports to whitelisted provider; per-tx cap 0.001 SOL; rate limit 100 tx / 60 slots |
| `log_compliance_event` | hardware_pubkey | Creates `ComplianceLog` PDA with telemetry hash; **no budget or rate checks** |
| `update_provider_whitelist` | owner | Add/remove provider from whitelist (max 8) |

---

## Events

| Event | Emitted by | Key fields |
|---|---|---|
| `ComputePaymentEvent` | `stream_compute_payment` | agent, provider, lamports, lamports_spent_total, slot |
| `ComplianceEvent` | `log_compliance_event` | agent, hash, severity, reason_code, slot, timestamp |

The dashboard subscribes to both via `program.addEventListener` / `onLogs`.

---

## Prerequisites

```bash
rustup toolchain install stable
sh -c "$(curl -sSfL https://release.solana.com/v1.18.26/install)"
avm install 1.0.0 && avm use 1.0.0  # Anchor CLI
```

---

## Build & Test

```bash
cd programs

# Build
anchor build

# Test on localnet (spins up solana-test-validator automatically)
anchor test

# Specific test file
pnpm exec mocha --require ts-node/register tests/agentic_hardware_bridge.ts
```

---

## Deploy to Devnet

```bash
# Set env vars
export HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=...
export DEPLOYER_KEYPAIR_PATH=~/.config/solana/id.json

../scripts/deploy_devnet.sh
# Writes program_id + timestamp to deployed.json
# Runs smoke test automatically
```

---

## Structure

```
programs/
├── programs/agentic_hardware_bridge/src/
│   ├── lib.rs                      Program entrypoint + instruction dispatch
│   ├── state.rs                    HardwareAgent / ComputeProvider / ComplianceLog structs
│   ├── events.rs                   ComputePaymentEvent / ComplianceEvent
│   ├── errors.rs                   AuxinError enum
│   └── instructions/
│       ├── initialize_agent.rs
│       ├── stream_compute_payment.rs
│       ├── log_compliance_event.rs
│       └── update_provider_whitelist.rs
├── tests/                          TypeScript test suite (Anchor + Mocha)
├── DESIGN.md                       PDA spec, space calculations, security notes
├── SECURITY.md                     Security checklist and cargo-audit results
└── deployed.json                   Program ID + cluster + deploy timestamp
```

---

## How It Fits

The Python bridge (`/sdk/src/auxin_sdk/bridge.py`) calls this program via `AuxinProgramClient` (`/sdk/src/auxin_sdk/program/client.py`). The dashboard (`/dashboard`) subscribes to its events via `@solana/web3.js` `onLogs`. See the [root architecture diagram](../README.md#architecture).

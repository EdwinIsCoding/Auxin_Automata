# agentic_hardware_bridge

Anchor Solana program. Handles autonomous M2M micropayments and immutable compliance logging for hardware agents. Deployed to Devnet.

→ [Root README](../README.md)

---

## Deployed

| Cluster | Program ID | Explorer |
|---|---|---|
| Devnet | `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm` | [View](https://explorer.solana.com/address/7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm?cluster=devnet) |
| Localnet | `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm` | — |

IDL Authority: `8bLUL5Ej8Q8bh4dJZzywj71kT5M8UsedTwDFFvrbzSDx` · Deployed: 2026-04-14

---

## Program Accounts

### HardwareAgent PDA
Seeds: `[b"agent", owner_pubkey]`

One per hardware device. Stores: hardware signing key, compute budget lamports, lamports spent, whitelisted provider list (max 8), rolling rate-limit window state (`last_window_start_slot`, `window_count`).

### ComputeProvider PDA
Seeds: `[b"provider", provider_pubkey]`

Tracks cumulative lamports received across all agents. Initialised lazily on first payment.

### ComplianceLog PDA
Seeds: `[b"log", agent_pda, slot.to_le_bytes()]`

Immutable. Stores: 64-char hex hash of raw telemetry frame, severity (0–3), reason_code, slot, timestamp. **No rate-limit or budget check on this account — ever.**

---

## Instructions

| Instruction | Signer | Description |
|---|---|---|
| `initialize_agent` | owner | Creates `HardwareAgent` PDA; funds compute budget |
| `stream_compute_payment` | hardware_pubkey | Transfers lamports to whitelisted provider; 0.001 SOL cap; 100 tx/60-slot rolling window |
| `log_compliance_event` | hardware_pubkey | Creates `ComplianceLog` PDA; **no budget or rate checks** |
| `update_provider_whitelist` | owner | Add / remove provider (max 8) |

---

## Events

| Event | Emitted by | Key fields |
|---|---|---|
| `ComputePaymentEvent` | `stream_compute_payment` | agent, provider, lamports, lamports_spent_total, slot |
| `ComplianceEvent` | `log_compliance_event` | agent, hash, severity, reason_code, slot, timestamp |
| `AgentInitializedEvent` | `initialize_agent` | owner, hardware_pubkey, compute_budget_lamports |
| `ProviderWhitelistUpdatedEvent` | `update_provider_whitelist` | agent, provider, action |

The dashboard subscribes to `ComputePaymentEvent` and `ComplianceEvent` via `@solana/web3.js` `connection.onLogs`.

---

## Prerequisites

```bash
# Rust stable
rustup toolchain install stable

# Solana CLI (Agave) 1.18+
sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)"

# Anchor via avm
cargo install --git https://github.com/coral-xyz/anchor avm --locked
avm install 0.30.1 && avm use 0.30.1
```

---

## Build & Test

```bash
cd programs

# Build — produces .so + IDL in target/
anchor build

# TypeScript tests (requires running validator)
solana-test-validator --reset --quiet &
sleep 15
anchor test --skip-local-validator
```

**23/23 TypeScript tests pass.** 1 test marked pending (rate-limit window roll — requires slot batching beyond localnet).

---

## Deploy to Devnet

```bash
export HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=...
../scripts/deploy_devnet.sh
# Idempotent — skips re-deploy unless --force is passed.
# Writes program_id + timestamp to deployed.json.
# Runs smoke_test_devnet.ts automatically.
```

---

## Security

- Every instruction validates the correct signer (`hardware_pubkey` for payment/compliance; `owner` for whitelist).
- No CPIs to untrusted programs — only `system_program::transfer`.
- All arithmetic uses `checked_add` / `checked_sub`; `overflow-checks = true` in release.
- All account constraints use `seeds`, `bump`, and `has_one` where applicable.
- Hash strings bounded to 64 chars before storage.
- `cargo clippy -- -D warnings` (with Anchor macro allowances): clean.

---

## Structure

```
programs/
├── programs/agentic_hardware_bridge/src/
│   ├── lib.rs                         Program entrypoint + instruction dispatch
│   ├── state.rs                       HardwareAgent / ComputeProvider / ComplianceLog
│   ├── events.rs                      Event structs
│   ├── errors.rs                      AuxinError enum
│   └── instructions/
│       ├── initialize_agent.rs
│       ├── stream_compute_payment.rs
│       ├── log_compliance_event.rs
│       └── update_provider_whitelist.rs
├── tests/
│   └── agentic_hardware_bridge.ts     TypeScript test suite (Anchor + Mocha)
└── deployed.json                      Program ID + cluster + deploy timestamp
```

---

## How It Fits

The Python bridge calls this program via `AuxinProgramClient` in `/sdk/src/auxin_sdk/program/client.py`. The dashboard subscribes to emitted events in `lib/useProgramEvents.ts`. See the [root architecture diagram](../README.md#architecture).

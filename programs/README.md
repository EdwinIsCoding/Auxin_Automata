# agentic_hardware_bridge

Anchor 1.0 Solana program. Handles autonomous M2M micropayments and immutable compliance logging for hardware agents.

→ [Root README](../README.md) · [PDA Design](./DESIGN.md) · [Security Checklist](./SECURITY.md)

---

## Deployed

| Cluster | Program ID | Explorer |
|---|---|---|
| Devnet | `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm` | [View](https://explorer.solana.com/address/7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm?cluster=devnet) |
| Localnet | `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm` | — |

IDL authority: `8bLUL5Ej8Q8bh4dJZzywj71kT5M8UsedTwDFFvrbzSDx` · Deployed: 2026-04-14

---

## Program Accounts

### HardwareAgent PDA
Seeds: `[b"agent", owner_pubkey]`

Represents one autonomous hardware device. Stores the hardware signing key, compute budget, lamports spent, whitelisted provider list (max 8), and rolling rate-limit window state (`last_window_start_slot`, `window_count`).

### ComputeProvider PDA
Seeds: `[b"provider", provider_pubkey]`

Tracks cumulative lamports received by a provider across all agents. Initialised lazily on first payment.

### ComplianceLog PDA
Seeds: `[b"log", agent_pda, slot.to_le_bytes()]`

Immutable record of one compliance event. Stores a 64-char hex hash of the raw telemetry frame, severity (0–3), and reason code. **Never rate-limited or budget-blocked** — this is the architectural guarantee.

---

## Instructions

| Instruction | Signer | Description |
|---|---|---|
| `initialize_agent` | owner | Creates `HardwareAgent` PDA; funds compute budget |
| `stream_compute_payment` | hardware_pubkey | Transfers lamports to a whitelisted provider; per-tx cap 0.001 SOL; 100 tx / 60-slot rolling window |
| `log_compliance_event` | hardware_pubkey | Creates `ComplianceLog` PDA with telemetry hash; **no budget or rate checks** |
| `update_provider_whitelist` | owner | Add / remove provider from whitelist (max 8) |

---

## Events

| Event | Emitted by | Key fields |
|---|---|---|
| `ComputePaymentEvent` | `stream_compute_payment` | agent, provider, lamports, lamports_spent_total, slot |
| `ComplianceEvent` | `log_compliance_event` | agent, hash, severity, reason_code, slot, timestamp |
| `AgentInitializedEvent` | `initialize_agent` | owner, hardware_pubkey, compute_budget_lamports |
| `ProviderWhitelistUpdatedEvent` | `update_provider_whitelist` | agent, provider, action |

The dashboard subscribes to `ComputePaymentEvent` and `ComplianceEvent` via `program.addEventListener` / `onLogs`.

---

## Prerequisites

```bash
# Rust toolchain
rustup toolchain install stable

# Solana CLI (Agave) 1.18+
sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)"

# Anchor CLI 1.0.0 via avm
cargo install --git https://github.com/coral-xyz/anchor avm --locked
avm install 1.0.0 && avm use 1.0.0
```

---

## Build & Test

```bash
cd programs

# Build (produces .so + IDL JSON in target/)
anchor build

# Unit tests — start a local validator first, then:
solana-test-validator --reset --quiet &
sleep 15
anchor test --skip-local-validator

# Or let Anchor manage the validator (requires surfpool):
anchor test
```

23/23 TypeScript tests pass. 1 test is marked pending (rate-limit window roll — requires batched slot injection beyond what localnet supports natively).

---

## Deploy to Devnet

```bash
export HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=...
export DEPLOYER_KEYPAIR_PATH=~/.config/solana/id.json

../scripts/deploy_devnet.sh
# Idempotent — skips re-deploy unless --force is passed.
# Writes program_id + timestamp to deployed.json.
# Runs smoke_test_devnet.ts automatically.
```

---

## Security

See [SECURITY.md](./SECURITY.md) for the full checklist. Summary:

- Every instruction validates the correct signer (`hardware_pubkey` for payment/compliance, `owner` for whitelist).
- No CPIs to untrusted programs — only `system_program::transfer`.
- All arithmetic uses `checked_add` / `checked_sub`; `overflow-checks = true` in release profile.
- All account constraints use `seeds`, `bump`, and `has_one` where applicable.
- Hash strings length-bounded to 64 chars before storage.
- `cargo audit`: 0 vulnerabilities (1 "unmaintained" advisory on `bincode` — transitive Anchor dependency, not actionable).
- `cargo clippy --all-targets -- -D warnings`: clean.

---

## Structure

```
programs/
├── programs/agentic_hardware_bridge/src/
│   ├── lib.rs                        Program entrypoint + instruction dispatch
│   ├── state.rs                      HardwareAgent / ComputeProvider / ComplianceLog structs
│   ├── events.rs                     Event structs
│   ├── errors.rs                     AuxinError enum
│   └── instructions/
│       ├── initialize_agent.rs
│       ├── stream_compute_payment.rs
│       ├── log_compliance_event.rs
│       └── update_provider_whitelist.rs
├── tests/
│   └── agentic_hardware_bridge.ts    TypeScript test suite (Anchor + Mocha)
├── DESIGN.md                         PDA spec, space calculations, account layout
├── SECURITY.md                       Security checklist and audit results
└── deployed.json                     Program ID + cluster + deploy timestamp
```

---

## How It Fits

The Python bridge (`/sdk/src/auxin_sdk/bridge.py`) calls this program via `AuxinProgramClient` (`/sdk/src/auxin_sdk/program/client.py`). The dashboard (`/dashboard`) subscribes to on-chain events via `@solana/web3.js` `onLogs`. See the [root architecture diagram](../README.md#architecture).

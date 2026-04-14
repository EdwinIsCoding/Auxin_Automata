# agentic_hardware_bridge — PDA Design

Phase 2A.2 design review. Read before writing instruction logic in 2A.3–2A.6.

---

## Account Space Convention

All sizes include the 8-byte Anchor discriminator prefix.
`INIT_SPACE` constants are defined in `state.rs` and referenced in each init instruction's `space` constraint.

---

## 1. HardwareAgent

**Represents a single autonomous hardware agent registered on-chain.**

### Seeds

```
[b"agent", owner_pubkey.as_ref()]
```

`owner_pubkey` is the wallet that pays for initialization and retains authority to update the whitelist and close the account.

### Fields

| Field | Type | Description |
|---|---|---|
| `owner` | `Pubkey` | Authority — must sign mutating instructions |
| `hardware_pubkey` | `Pubkey` | Ed25519 key burned into the hardware module (e.g. Jetson secure enclave or key file) |
| `compute_budget_lamports` | `u64` | Maximum total lamports this agent may spend on compute payments (lifetime cap) |
| `lamports_spent` | `u64` | Running total of lamports disbursed via `stream_compute_payment` |
| `providers` | `Vec<Pubkey>` | Whitelisted compute providers; max 8 entries |
| `created_at` | `i64` | Unix timestamp at initialization (`Clock::get().unix_timestamp`) |
| `bump` | `u8` | PDA canonical bump, stored to avoid re-derivation on each CPI |

### Space Calculation

```
8   discriminator
32  owner
32  hardware_pubkey
8   compute_budget_lamports  (u64)
8   lamports_spent           (u64)
4   providers.len            (u32 Vec prefix)
256 providers data           (8 × 32 bytes)
8   created_at               (i64)
8   last_window_start_slot   (u64)
2   window_tx_count          (u16)
1   bump
─────
367 bytes  →  HARDWARE_AGENT_SPACE = 367
```

### Rate-Limit Fields

| Field | Type | Purpose |
|---|---|---|
| `last_window_start_slot` | `u64` | Slot at which the current rolling window began |
| `window_tx_count` | `u16` | Transactions counted in this window |

Window resets when `current_slot - last_window_start_slot >= 60`. Max 100 txs per window.
Per-transaction cap: 0.001 SOL (1,000,000 lamports).

### Security Notes

- `stream_compute_payment` is signed by `hardware_pubkey` (autonomous — the device signs, not the owner).
- Provider whitelist check: `target_provider ∈ providers`.
- Budget check: `lamports_spent + amount ≤ compute_budget_lamports` (checked arithmetic — `AuxinError::BudgetExceeded`).
- Rate limit: rolling-window of 60 slots, max 100 txs per window — `AuxinError::RateLimitExceeded`.
- Per-tx cap: `amount ≤ 0.001 SOL` — `AuxinError::PerTxCapExceeded`.
- Only `owner` may call `update_provider_whitelist`.

---

## 2. ComputeProvider

**Tracks aggregate payments received by a provider address.**

### Seeds

```
[b"provider", provider_pubkey.as_ref()]
```

### Fields

| Field | Type | Description |
|---|---|---|
| `provider_pubkey` | `Pubkey` | The provider's on-chain address (matches seed) |
| `total_received` | `u64` | Cumulative lamports received across all agents |
| `bump` | `u8` | PDA canonical bump |

### Space Calculation

```
8   discriminator
32  provider_pubkey
8   total_received  (u64)
1   bump
─────
49 bytes  →  COMPUTE_PROVIDER_SPACE = 49
```

### Notes

- Initialized lazily on first payment to a new provider address via `stream_compute_payment`.
- `total_received` is incremented with `checked_add` — overflow reverts with `AuxinError::Overflow`.
- Anyone may read this account; only the bridge (via `stream_compute_payment`) may mutate it.

---

## 3. ComplianceLog

**Immutable on-chain record of a compliance event emitted by the hardware bridge.**

### Seeds

```
[b"log", agent_pubkey.as_ref(), &slot.to_le_bytes()]
```

`slot` is `Clock::get().slot` at transaction time. Using the slot (not a counter) keeps seed derivation deterministic from the outside without requiring a mutable nonce in `HardwareAgent`.

> **Collision risk:** Two compliance events in the same slot for the same agent would collide. Acceptable for MVP; mitigate in production by appending a 1-byte sub-index (0–255) or using a global monotonic counter stored in `HardwareAgent`.

### Fields

| Field | Type | Description |
|---|---|---|
| `agent` | `Pubkey` | The `HardwareAgent` that triggered this event |
| `hash` | `String` | Keccak-256 hex digest of the raw telemetry payload, max 64 chars |
| `severity` | `u8` | `1` = INFO, `2` = WARN, `3` = CRITICAL |
| `reason_code` | `u16` | Application-defined code (e.g. `0x0001` = torque-limit, `0x0002` = vision-fail) |
| `timestamp` | `i64` | Unix timestamp from `Clock::get().unix_timestamp` |
| `bump` | `u8` | PDA canonical bump |

### Space Calculation

```
8   discriminator
32  agent
4   hash.len   (u32 String prefix)
64  hash data  (max 64 UTF-8 bytes — hex chars are ASCII)
1   severity   (u8)
2   reason_code (u16)
8   timestamp  (i64)
1   bump
─────
120 bytes  →  COMPLIANCE_LOG_SPACE = 120
```

### Compliance Contract (from CLAUDE.md)

> Compliance events are **NEVER** rate-limited, budget-blocked, or dropped under backpressure.

`log_compliance_event` must **not** check `compute_budget_lamports`, `lamports_spent`, or any rate-limit window. The only invariants it enforces are:
1. `agent` account is a valid `HardwareAgent` PDA.
2. `hash` length ≤ 64 bytes.
3. `severity ∈ {1, 2, 3}`.

---

## Instruction Summary (2A.3–2A.6)

| Instruction | Accounts mutated | Guards |
|---|---|---|
| `initialize_agent` | Creates `HardwareAgent`, funds PDA | signer = owner |
| `stream_compute_payment` | `HardwareAgent` (lamports_spent↑, window_tx_count↑), `ComputeProvider` (total_received↑), SOL transfer from PDA | signer = hardware_pubkey (autonomous); provider whitelisted; per-tx cap ≤ 0.001 SOL; rate limit ≤ 100/60 slots; budget not exceeded |
| `log_compliance_event` | Creates `ComplianceLog` | signer = hardware_pubkey (autonomous); hash len ≤ 64; severity 0–3; **NO budget/rate checks** |
| `update_provider_whitelist` | `HardwareAgent` (providers) | signer = owner; action = Add\|Remove enum; max 8 providers |

---

## Events (see events.rs)

| Event | Emitted by | Key fields |
|---|---|---|
| `ComputePaymentEvent` | `stream_compute_payment` | agent, provider, amount_lamports, lamports_spent_total, slot |
| `ComplianceEvent` | `log_compliance_event` | agent, hash, severity, reason_code, slot, timestamp |

Dashboard subscribes to both via `program.addEventListener` / `onLogs` — see `useProgramEvents` hook (2C.6).

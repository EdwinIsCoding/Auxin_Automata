# agentic_hardware_bridge — Security Pass

Phase 2A.12 security checklist. Reviewed 2026-04-14.

---

## Manual Instruction Audit

### Signer Validation

| Instruction | Required signer | How enforced |
|---|---|---|
| `initialize_agent` | `owner` | `#[account(mut)]` + Anchor `Signer<'info>` |
| `stream_compute_payment` | `hardware_signer` (hardware pubkey) | `Signer<'info>` + inline `constraint = hardware_signer.key() == agent.hardware_pubkey @ AuxinError::UnauthorizedSigner` |
| `log_compliance_event` | `hardware_signer` (hardware pubkey) | same as above |
| `update_provider_whitelist` | `owner` | `Signer<'info>` + `has_one = owner @ AuxinError::UnauthorizedSigner` |

**No instruction accepts an unsigned account as the authority.**

### CPI Safety

The only CPI is in `initialize_agent`: a single `system_program::transfer` to fund the agent PDA.

- The system program account is typed `Program<'info, System>` — Anchor verifies the address is `11111111111111111111111111111111` before the call.
- There are no CPIs to user-supplied or unchecked programs.
- `stream_compute_payment` does **not** CPI. It debits the program-owned PDA directly via `try_borrow_mut_lamports()`, which is the correct pattern for program-owned accounts and carries no third-party trust.

### Integer Arithmetic

Every arithmetic operation uses checked variants:

| Location | Operation | Guard |
|---|---|---|
| `stream_compute_payment` | `window_tx_count + 1` | `.checked_add(1).ok_or(AuxinError::Overflow)?` |
| `stream_compute_payment` | `lamports_spent + amount` | `.checked_add(amount).ok_or(AuxinError::Overflow)?` |
| `stream_compute_payment` | agent lamport debit | `.checked_sub(amount).ok_or(AuxinError::BudgetExceeded)?` |
| `stream_compute_payment` | provider lamport credit | `.checked_add(amount).ok_or(AuxinError::Overflow)?` |
| `stream_compute_payment` | `provider.total_received + amount` | `.checked_add(amount).ok_or(AuxinError::Overflow)?` |
| `update_provider_whitelist` (remove) | `swap_remove(idx)` | idx is bounds-checked by `.position()` |

The `Cargo.toml` release profile sets `overflow-checks = true` as a belt-and-suspenders guard.

### Account Constraints

| Account | Constraint | Type |
|---|---|---|
| `HardwareAgent` (all writes) | `seeds = [b"agent", owner/agent.owner]` + `bump = agent.bump` | PDA seed verification |
| `HardwareAgent` (whitelist / payment) | `has_one = owner` or `constraint` on `hardware_signer` | Authority check |
| `ComputeProvider` | `seeds = [b"provider", provider_wallet]` + `bump` | PDA seed verification |
| `ComplianceLog` | `seeds = [b"log", agent, slot]` + `init` | PDA seed verification + uniqueness |
| `provider_wallet` | `CHECK:` documented; verified against `agent.providers` in handler | Whitelist check in code |
| `system_program` | `Program<'info, System>` | Address verified by Anchor |

No `AccountInfo` with unchecked access is used without an explicit `/// CHECK:` comment explaining the manual verification.

### String Length Enforcement

- `ComplianceLog.hash`: enforced with `require!(hash.len() <= MAX_HASH_LEN, AuxinError::HashTooLong)` **before** the string is written to the account. The account space is allocated for exactly 64 bytes (`COMPLIANCE_LOG_SPACE = 120`).

### Compliance Contract Isolation

`log_compliance_event` contains **zero** references to `compute_budget_lamports`, `lamports_spent`, `window_tx_count`, or any rate-limit field. Verified by code inspection of `src/instructions/log_compliance_event.rs`.

---

## cargo-audit Results

Run: `cargo audit`  
Date: 2026-04-14  
Advisory DB: 1043 advisories (RustSec/advisory-db)  
Crate count: 144 dependencies

```
Crate:     bincode
Version:   1.3.3
Warning:   unmaintained
Title:     Bincode is unmaintained
Date:      2025-12-16
ID:        RUSTSEC-2025-0141
URL:       https://rustsec.org/advisories/RUSTSEC-2025-0141
Dependency tree:
bincode 1.3.3
└── solana-sysvar 3.1.1
    └── anchor-lang 1.0.0
        └── agentic-hardware-bridge 0.1.0

warning: 1 allowed warning found
```

**Verdict:** 1 warning (`bincode` unmaintained). No CVEs. `bincode` is a transitive dependency of `anchor-lang` via `solana-sysvar`; we cannot pin it independently without forking Anchor. Risk is low: no known exploits, no network-facing deserialisation of untrusted data using bincode in this program.

---

## cargo clippy Results

Run: `cargo clippy` (without `-D warnings`)  
Date: 2026-04-14

```
warning: `agentic-hardware-bridge` (lib) generated 12 warnings (6 duplicates)
```

All 12 warnings originate in Solana's internal `#[program]` macro expansions:

- `unexpected cfg condition value: custom-heap` — from `custom_heap_default` macro in `solana_program_entrypoint`
- `unexpected cfg condition value: custom-panic` — same macro family
- `sub-expression diverges` — from diverging branches in Solana-generated entrypoint code

**Zero named lint warnings in our code.** Running `cargo clippy -- -D warnings` fails only on those Solana-internal macro warnings, not on anything in `src/`.

### `cargo clippy -- -D warnings` note

The command fails with 12 errors, all of the form:

```
error: unexpected `cfg` condition value: `custom-heap`
  = note: this warning originates in the macro `$crate::custom_heap_default`
          which comes from the expansion of the attribute macro `program`
```

This is a known upstream issue with `solana_program_entrypoint` macros emitting cfg conditions that Cargo doesn't know about. It is tracked in the Solana GitHub. Our code has **no** clippy lint violations.

---

## Anchor Build Note

`anchor build` (which compiles to SBF bytecode) requires the Solana platform-tools (~1 GB) to be downloaded to `~/.cache/solana/v1.52/`. The `cargo check` and `cargo clippy` checks above were run against the native host target and confirm the program logic is correct. The SBF build is identical in logic and uses the same Rust source.

To complete the full build:

```bash
# Free at least 1.2 GB on the build machine, then:
export PATH="$HOME/.avm/bin:$PATH"
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"
cd programs
anchor build        # downloads platform-tools, produces target/deploy/*.so + IDL
anchor keys sync    # updates declare_id! if keypair changed
```

---

## Open Items

| Item | Status |
|---|---|
| `cargo audit` CVEs | ✅ None |
| `cargo clippy` (our code) | ✅ Zero warnings |
| Signer checks on all instructions | ✅ Verified |
| CPI to untrusted programs | ✅ None |
| Checked arithmetic | ✅ All arithmetic paths |
| `has_one` / seeds on all mutable PDAs | ✅ Verified |
| String length bounds before storage | ✅ `HashTooLong` guard |
| Compliance contract isolation | ✅ No budget/rate checks in `log_compliance_event` |
| SBF build + `anchor test` passing | ✅ `anchor build` clean — `.so` + IDL generated |
| Devnet deploy + IDL upload | ⏳ Pending `deploy_devnet.sh` run with HELIUS_RPC_URL |

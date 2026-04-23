# MagicBlock Side Track Submission — Auxin Automata

## Project

**Auxin Automata** — autonomous hardware wallets with M2M micropayments and immutable safety compliance on Solana.

**One-liner:** The first autonomous robotic hardware system to route M2M micropayments through MagicBlock's Private Ephemeral Rollup — zero per-payment on-chain footprint, AML screening on every payment, no human in the payment loop.

## Links

- **Repository:** https://github.com/EdwinIsCoding/auxin-automata
- **Devnet Program:** [`7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm`](https://explorer.solana.com/address/7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm?cluster=devnet)
- **MagicBlock API:** `https://payments.magicblock.app`
- **Integration docs:** [`docs/privacy-magicblock.md`](../privacy-magicblock.md)

## What We Built with MagicBlock

### The integration

`MagicBlockProvider` (`sdk/src/auxin_sdk/privacy/magicblock.py`) implements the `PrivacyProvider` ABC.  When `AUXIN_PRIVACY=magicblock`:

1. The bridge calls `MagicBlockProvider.send_payment()` after each Gemini oracle approval.
2. The provider calls `POST /v1/spl/transfer` on `payments.magicblock.app` with owner, destination (compute provider), amount, mint (wSOL), and `privacy: "private"`.
3. MagicBlock returns an unsigned Solana transaction.  AML screening (Range) runs at this step — rejected payments return HTTP 400 before any on-chain action.
4. The provider signs the transaction with the hardware wallet's keypair (solders `VersionedTransaction`) and submits to Solana or the rollup validator indicated by the response's `sendTo` field.
5. `PaymentResult(is_private=True, privacy_provider="magicblock")` is returned.  The dashboard shows a lock icon.

**Budget pre-delegation:** `delegate_budget(wallet, lamports)` calls `POST /v1/spl/deposit` to fund the rollup pool once.  Subsequent `send_payment()` calls draw from this pool — no per-payment deposit transaction.  This is critical for machine-rate payment flows: a robot arm making one payment per 100ms cannot afford a separate deposit round-trip per payment.

**Fallback:** Any API failure (network error, AML rejection, timeout) falls back to `DirectProvider` with a warning log.

**Tests:** `sdk/tests/test_magicblock_provider.py` — 9 tests covering successful result, metadata shape, idempotent skip, fallback on HTTP 400 (AML rejection), fallback on network error, error propagation without fallback, `delegate_budget` calling `/v1/spl/deposit`, API key forwarded as Bearer token, and compliance bypass.

### What problem it solves

Autonomous hardware operating at machine frequency creates a payment stream that is a public ledger of operational intelligence.  MagicBlock's Private Ephemeral Rollup eliminates the per-payment on-chain footprint entirely — individual payments settle inside the TEE, and only the batch settlement transaction is visible on Solana.

This is the strongest operational-pattern hiding of the three privacy providers: an observer cannot even count individual payments, let alone identify the provider.

### The AML angle — a feature, not a limitation

MagicBlock enforces AML compliance at the API layer via Range: OFAC sanctions screening, counterparty risk assessment, and behavioural signal analysis.  Every call to `POST /v1/spl/transfer` is screened before any transaction is built.

For Auxin Automata, this is a competitive narrative point: **every autonomous M2M payment is AML-screened without any additional operator-side infrastructure.**  The operator does not run a compliance oracle for payments.  MagicBlock's API enforces it.  For industrial operators deploying autonomous hardware at scale — where adding a compliance stack per device is economically infeasible — AML-as-a-service at the payment layer is the right abstraction.

The submission narrative: "a robot arm making thousands of daily payments, each individually AML-screened by MagicBlock before execution, with no per-payment on-chain trace."

### Why M2M hardware payments are a novel use case for MagicBlock

MagicBlock's Private Ephemeral Rollup is designed for gaming transactions and high-frequency DeFi.  Auxin Automata demonstrates a third vertical:

- **Machine-initiated, not user-initiated.**  No wallet confirmation dialog, no user latency.  The hardware wallet signs immediately after oracle approval.
- **Volume that justifies pre-delegation.**  A robot arm running 8 hours at 10 Hz with 50% oracle approval = ~144,000 payment intents per day.  Pre-delegating a batch budget is not a convenience — it is architecturally necessary at this frequency.
- **Safety-layer separation.**  `log_compliance_event` always goes to the public chain, bypassing MagicBlock entirely.  Privacy covers the economic layer; the safety layer remains fully public and auditable.  This separation is enforced in code and tested.
- **Autonomous fleet economics.**  A fleet of 10 arms each making ~144,000 payments per day would produce ~1.44M visible on-chain transactions per day without privacy.  With MagicBlock, the entire fleet produces only periodic batch settlement transactions.

# Cloak Side Track Submission — Auxin Automata

## Project

**Auxin Automata** — autonomous hardware wallets with M2M micropayments and immutable safety compliance on Solana.

**One-liner:** The first autonomous robotic hardware system to stream private M2M micropayments on Solana — robot arms paying compute providers through Cloak's ZK shield pool, with zero human intervention in the signing or payment loop.

## Links

- **Repository:** https://github.com/EdwinIsCoding/auxin-automata
- **Devnet Program:** [`7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm`](https://explorer.solana.com/address/7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm?cluster=devnet)
- **Cloak Program (devnet + mainnet):** `zh1eLd6rSphLejbFfJEneUwzHRfMKxgzrgkfwA6qRkW`
- **Integration docs:** [`docs/privacy-cloak.md`](../privacy-cloak.md)

## What We Built with Cloak

### The integration

`CloakProvider` (`sdk/src/auxin_sdk/privacy/cloak.py`) implements the `PrivacyProvider` ABC that drives every payment in the bridge.  When `AUXIN_PRIVACY=cloak`:

1. The bridge calls `CloakProvider.send_payment()` after each Gemini oracle approval.
2. The provider calls a Node.js subprocess (`cloak_bridge/deposit.mjs`) via `asyncio.create_subprocess_exec` — JSON over stdin/stdout.
3. The subprocess calls `@cloak.dev/sdk`: `generateUtxoKeypair()` → `createUtxo()` → `transact()` to deposit into the shield pool.
4. The UTXO commitment and private key are returned to Python, stored in `PaymentResult.metadata`.
5. The dashboard renders a lock icon in `PaymentTicker` when `is_private=True`.

**Viewing key support:** `cloak_bridge/keygen.mjs` generates UTXO keypairs and derives viewing keys via `getNkFromUtxoPrivateKey()` + `deriveViewingKeyFromNk()`.  The operator runs `scripts/setup_cloak_provider.py` once to register their Cloak identity; the viewing key is stored at `~/.config/auxin/cloak_provider.json` and can be shared with auditors.

**Fallback:** If the Node.js subprocess fails for any reason (relayer down, ZK proof timeout, Node.js not installed), the provider falls back to `DirectProvider` with a warning log.  The demo never stalls.

**Tests:** `sdk/tests/test_cloak_provider.py` — 8 tests covering successful result shape, unique UTXOs per payment, idempotent skip, fallback on error, error propagation without fallback, node-not-found error, timeout, and compliance bypass (verifying Cloak is never called for compliance events).

### What problem it solves

A robot arm making 5,000 micropayments per day to a compute provider creates a high-resolution public log of its operational pattern.  An observer can identify the compute provider, estimate throughput, detect business relationships, and front-run pricing negotiations — all from public blockchain data.

Cloak eliminates this leakage.  Each payment deposits into the shield pool as an unlinkable UTXO.  The provider detects payments via their viewing key and batch-withdraws.  The on-chain record reveals that *someone* is using the pool, but not *which hardware operator* is paying *which provider* or *how often*.

### Why M2M hardware payments are a novel use case

Cloak was designed for human-to-human private payments — a user shielding a salary, a business hiding supplier payments.  Auxin Automata is the first integration where:

- **The sender is a machine, not a human.**  The hardware wallet signs autonomously after each oracle approval; no human initiates the payment.
- **Payment frequency is machine-rate.**  Thousands of payments per day, each triggered by a safety oracle, each one potentially revealing operational intelligence to a public ledger observer.
- **The privacy requirement is competitive, not personal.**  The goal is not user anonymity in the traditional sense — it is preventing competitive analysis of autonomous hardware fleet operations from public blockchain data.
- **Compliance and privacy are orthogonal.**  Compliance events (safety anomaly hashes) always go to the public chain via `log_compliance_event`, bypassing Cloak entirely.  Privacy applies only to the economic layer.

This is machine-rate streaming payment privacy — a use case that scales by order-of-magnitude faster than human payment flows and that existing private payment integrations are not optimised for.

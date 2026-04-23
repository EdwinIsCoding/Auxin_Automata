# Umbra Side Track Submission — Auxin Automata

## Project

**Auxin Automata** — autonomous hardware wallets with M2M micropayments and immutable safety compliance on Solana.

**One-liner:** The first autonomous robotic hardware system to route M2M micropayments through Umbra's unified mixer pool — individual robot payments become indistinguishable in the pool, with time-scoped selective disclosure for regulators.

## Links

- **Repository:** https://github.com/EdwinIsCoding/auxin-automata
- **Devnet Program:** [`7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm`](https://explorer.solana.com/address/7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm?cluster=devnet)
- **Umbra Program (devnet):** [`DSuKkyqGVGgo4QtPABfxKJKygUDACbUhirnuv63mEpAJ`](https://explorer.solana.com/address/DSuKkyqGVGgo4QtPABfxKJKygUDACbUhirnuv63mEpAJ?cluster=devnet)
- **Umbra Program (mainnet):** `UMBRAD2ishebJTcgCLkTkNUx1v3GyoAgpTRPeWoLykh`
- **Integration docs:** [`docs/privacy-umbra.md`](../privacy-umbra.md)

## What We Built with Umbra

### The integration

`UmbraProvider` (`sdk/src/auxin_sdk/privacy/umbra.py`) implements the `PrivacyProvider` ABC.  Because `@umbra-privacy/sdk` is TypeScript, we built a **persistent Express sidecar** (`/services/umbra-bridge/server.mjs`) that wraps the SDK and serves HTTP endpoints on localhost.  When `AUXIN_PRIVACY=umbra`:

1. The bridge calls `UmbraProvider.send_payment()` after each Gemini oracle approval.
2. The provider calls `POST /deposit` on the sidecar (localhost:3002).
3. The sidecar calls `getPublicBalanceToSelfClaimableUtxoCreatorFunction` from `@umbra-privacy/sdk` with `getPublicBalanceToSelfClaimableUtxoCreatorProver()` from `@umbra-privacy/web-zk-prover`.
4. The ZK proof is generated (~1–5s), a UTXO commitment is appended to Umbra's Merkle tree, and the transaction is submitted to Solana.
5. `PaymentResult(is_private=True, privacy_provider="umbra", metadata={"utxo_commitment": ...})` is returned.  The dashboard shows a lock icon.

**Sidecar design:** A persistent sidecar rather than a subprocess-per-payment. The Umbra client caches its master seed derivation (one wallet signature) across all calls.  The ZK prover warms up once.  For machine-rate payment flows, re-initializing a full Umbra client per payment would be prohibitively slow.

**Selective disclosure:**
- `UmbraProvider.export_viewing_key(wallet, scope, year, month, day)` calls `POST /viewing-key` on the sidecar.
- The sidecar calls `getViewingKeyDeriverFunction` from `@umbra-privacy/sdk` to derive a time-scoped Transaction Viewing Key (TVK) from the Master Viewing Key.
- `scripts/setup_umbra_viewing_key.py` is a CLI that generates and writes the TVK to `~/.config/auxin/umbra_viewing_key.json` (chmod 600).

**Fallback:** Any sidecar failure falls back to `DirectProvider`.  Startup health check (`GET /health`) warns if the sidecar is unreachable but does not block the bridge.

**Tests:** `sdk/tests/test_umbra_provider.py` — 10 tests covering successful result, metadata shape (utxo_commitment, mint, provider_pubkey), idempotent skip, fallback on HTTP 500, fallback on network error, error propagation without fallback, health check true/false, viewing key export, and compliance bypass.

### What problem it solves

Umbra's mixer pool provides anonymity that grows with every participant.  A robot arm depositing 5,000 lamports is indistinguishable from every other 5,000-lamport deposit in the pool — whether from another robot arm, a DeFi protocol, or a human user.  The larger the pool, the stronger the anonymity guarantee for every participant.

Machine-rate M2M payments are an ideal workload for a mixer pool: they are high-volume, fixed-amount, and frequent.  A fleet of autonomous arms contributes thousands of deposits per day, directly strengthening the anonymity set for all Umbra users — the hardware operator benefits from and contributes to the shared pool.

### The selective disclosure story — purpose-built for autonomous industrial operations

Industrial hardware operators face regulators who need to verify that payment flows match compliance records.  Umbra's hierarchical Transaction Viewing Key system is the right answer:

- An operator running autonomous arms can give a **yearly TVK** to their annual auditor — access to every UTXO created in calendar year 2026, nothing else.
- A regulator investigating a specific incident can receive a **daily TVK** for the day in question — cryptographically scoped, non-revocable, non-transferable to adjacent periods.
- The TVK grants read access to UTXO amounts, timestamps, and commitments, but **cannot authorise spending** and **cannot derive the Master Viewing Key**.

This is selective disclosure that is technically enforced, not policy-enforced.  The auditor cannot see more than they are given; the operator cannot later claim the auditor had no access.  For a regulated industry like industrial robotics — where liability questions follow every autonomous action — this is a meaningful cryptographic guarantee.

### Why M2M hardware payments are a novel use case for Umbra

Umbra is designed for DeFi protocols and privacy-conscious individuals.  Auxin Automata demonstrates a fundamentally different actor:

- **Machine-initiated payments at hardware frequency.**  No user prompt, no confirmation latency.  Every oracle-approved action triggers a payment within the same async pipeline that processes the telemetry frame.
- **Anonymity as a fleet property.**  A single arm contributes ~144,000 deposits per day to the pool at 10 Hz with 50% oracle approval rate.  A fleet of 10 arms contributes ~1.44M deposits per day — a meaningful contribution to Umbra's global anonymity set.
- **Regulatory-grade selective disclosure.**  Industrial operators need to prove payment history to regulators on demand.  Umbra's time-scoped TVK system provides exactly this: cryptographic proof of payment activity for a specific period, without exposing the full operational record.
- **Safety-compliance separation.**  Compliance events (`log_compliance_event`) bypass Umbra and go directly to the public chain.  The UTXO mixer makes payments private; the compliance PDA makes safety records public.  Both guarantees are enforced in code and tested — not just documented.
- **First use of `createSignerFromPrivateKeyBytes` in a server-side autonomous payment context.**  The Umbra SDK's in-memory signer was designed for user-initiated flows.  We use it for a machine-initiated autonomous payment pipeline where the keypair is loaded from a hardware wallet file at startup and reused for the lifetime of the process.

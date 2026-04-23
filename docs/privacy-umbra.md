# Private Payments with Umbra

## What is Umbra?

[Umbra](https://umbraprivacy.com) is the financial privacy layer for Solana, built on
[Arcium](https://arcium.com)'s multi-party computation (MPC) network.  It provides
confidential, unlinkable, and auditable token transfers through two complementary
mechanisms:

- **Encrypted Token Accounts (ETAs)**: Confidential balances where amounts are encrypted
  on-chain via MPC — observers see the account exists but not the balance.
- **Unified Mixer Pool**: A shared on-chain pool backed by Merkle trees and Groth16 ZK
  proofs that severs the link between deposits and withdrawals.

Auxin Automata uses the **mixer pool** for M2M payments — individual robot micro-payments
become indistinguishable from every other deposit in the pool.

### Program IDs

| Network | Address |
|---|---|
| Mainnet | `UMBRAD2ishebJTcgCLkTkNUx1v3GyoAgpTRPeWoLykh` |
| Devnet | `DSuKkyqGVGgo4QtPABfxKJKygUDACbUhirnuv63mEpAJ` |

### SDK

| Package | Install |
|---|---|
| `@umbra-privacy/sdk` | `pnpm add @umbra-privacy/sdk` |
| `@umbra-privacy/web-zk-prover` | `pnpm add @umbra-privacy/web-zk-prover` |

TypeScript SDK — works in Node.js >=18 and modern browsers.  No native dependencies;
all cryptography is pure TypeScript/WebAssembly.

## How the Mixer Pool Works

### Deposit (UTXO Creation)

When SOL is deposited into the pool:

1. A **UTXO commitment** is computed — a Poseidon hash of the amount, a random secret,
   the unlocking address (spending authority), and the destination address (where funds
   go on withdrawal).
2. The commitment is appended as a leaf to an on-chain **Merkle tree** (depth 20,
   ~1M leaves per tree, up to 2^128 trees).
3. A **mixing delay** is enforced before the UTXO can be burned — this lets additional
   deposits accumulate, growing the anonymity set.

### Withdrawal (UTXO Burn)

To withdraw, the owner generates a **Groth16 ZK proof** demonstrating:

- **Membership**: the UTXO commitment exists in the Merkle tree.
- **Ownership**: the prover knows the secret inputs behind the unlocking address.
- **Nullifier correctness**: the nullifier is correctly derived from the UTXO and
  spending key.
- **Destination match**: funds release to the address fixed at deposit time.

The nullifier is published on-chain (preventing double-spend), and tokens are released
to the destination ATA.  The on-chain observer sees a withdrawal but **cannot link it
to any specific deposit**.

### Anonymity Set

Your anonymity set is every UTXO in the pool.  Larger pool, longer holding period,
common withdrawal amounts, and random timing all strengthen privacy.  Autonomous M2M
micro-payments are ideal — they're frequent, small, and naturally blend with each other.

## Why Pool-Based Privacy Suits M2M Payments

Auxin Automata streams thousands of micro-payments per day from robot arms to compute
providers.  In a pool:

- **Individual payments are indistinguishable** — a 5,000 lamport deposit from Robot A
  looks identical to a 5,000 lamport deposit from Robot B.
- **Payment frequency is hidden** — deposits can be batched or staggered without
  revealing the underlying operational tempo.
- **The anonymity set grows with usage** — as more autonomous agents use the pool,
  privacy compounds for everyone.

### On-Chain Footprint Comparison

| Mode | Per-payment on-chain footprint |
|---|---|
| `direct` | One tx per payment — sender, receiver, amount visible |
| `cloak` | One ZK deposit per payment — amount hidden, receiver unlinkable |
| `magicblock` | Zero per-payment txs — only batch settlement visible |
| `umbra` | One Merkle leaf per payment — unlinkable, subject to mixing delay |

## Selective Disclosure for Auditors

Umbra implements a hierarchical **Transaction Viewing Key (TVK)** system derived from
the user's **Master Viewing Key (MVK)**.  The MVK is a 252-bit BN254 scalar
deterministically derived from the wallet signature during Umbra client initialization.

### Key Hierarchy

```
Master Viewing Key (MVK)
    │
    ├── Mint-scoped key (per token)
    │   ├── Yearly TVK  = Poseidon(MVK, year)
    │   │   ├── Monthly TVK = Poseidon(yearly, month)
    │   │   │   └── Daily TVK = Poseidon(monthly, day)
    │   │   └── ...
    │   └── ...
    └── ...
```

### Properties

- **Hierarchical**: a parent key can derive all children (yearly → monthly → daily).
- **One-way**: a child key cannot derive its parent or the MVK.
- **Time-scoped**: each TVK only decrypts mixer activity within its time window.
- **Non-revocable**: once shared, a viewing key grants permanent read access to its
  scope — creating a non-repudiation guarantee for both parties.

### For Operators

Generate a scoped viewing key for your auditor:

```bash
python scripts/setup_umbra_viewing_key.py \
  --scope yearly --year 2026 \
  --output ~/.config/auxin/umbra_viewing_key_2026.json
```

Share the output file.  The auditor can verify every UTXO you created in the mixer
pool during 2026 — amounts, timestamps, commitments — without spending authority.

### For Auditors

With the viewing key, an auditor can:

1. **Verify every deposit** — amount, UTXO commitment, Merkle tree index.
2. **Cross-reference with compliance logs** — compliance events are on-chain PDAs
   logged via `log_compliance()`, independent of any privacy provider.
3. **Cannot spend funds** — the viewing key grants read access only.
4. **Cannot forge deposits** — the viewing key cannot create new UTXOs.

## Sidecar Architecture

The Umbra SDK (`@umbra-privacy/sdk`) is TypeScript.  Rather than a subprocess per
call (like the Cloak bridge), Umbra uses a **persistent Express sidecar** that starts
alongside the bridge and serves HTTP endpoints on localhost:

```
Python Bridge                       Node.js Sidecar
──────────────                      ──────────────────────
UmbraProvider                       /services/umbra-bridge/
    │                                     │
    ├─▶ POST /deposit ─────▶ Express ─▶ @umbra-privacy/sdk
    │                                   createUtxo()
    │                                   ZK proof (1–5s)
    │                                     │
    ◀── { signature, utxo_commitment } ◀──┘
    │
    ├─▶ POST /withdraw ────▶ Express ─▶ @umbra-privacy/sdk
    │                                   claimUtxo()
    │                                   ZK proof (1–5s)
    │                                     │
    ◀── { signature } ◀───────────────────┘
    │
    └─▶ POST /viewing-key ─▶ Express ─▶ deriveViewingKey()
                                          │
         ◀── { viewing_key, scope } ◀─────┘
```

### Why a Sidecar Instead of a Subprocess?

| Concern | Subprocess (Cloak) | Sidecar (Umbra) |
|---|---|---|
| Cold start | Every payment spawns Node.js (~300ms) | One startup; requests are instant |
| ZK prover cache | Lost between calls | Persisted across calls |
| Client state | Re-created each call (wallet signature prompt) | Cached after first use |
| Complexity | Simpler (single script) | Slightly more infra (Docker) |

For Cloak's single-deposit model, a subprocess is fine.  For Umbra's deposit + withdraw +
viewing-key flow — with ZK prover warmup — a persistent sidecar avoids redundant work.

### Compliance Architecture

```
Bridge._payment_worker
    │
    ▼  AUXIN_PRIVACY=umbra
UmbraProvider.send_payment()
    │
    ├─▶ POST /deposit → sidecar → Umbra SDK
    │                               │
    │                    ZK proof + Merkle insert
    │                               │
    ◀── { signature, utxo_commitment }
    │
    │   (mixing delay enforced by protocol)
    │
    ├─▶ POST /withdraw  → sidecar → Umbra SDK  (claim phase, async)
    │
    └── PaymentResult(is_private=True, privacy_provider="umbra")


Bridge._compliance_worker ──▶ ALWAYS public chain (bypasses Umbra)
    │
    ▼
log_compliance() → ComplianceLog PDA (immutable, on-chain)
```

**Key invariant:** Compliance events are **NEVER** routed through UmbraProvider.
Compliance hashes are public on-chain evidence; only M2M streaming payments are privatised.

## Enabling Umbra Payments

### Prerequisites

- Docker (for the sidecar) or Node.js >=20 (to run the sidecar directly)
- `pnpm` (for installing sidecar dependencies)
- Devnet SOL in the hardware wallet's ATA

### Setup

```bash
# 1. Start the sidecar (with docker-compose)
docker-compose -f docker-compose.demo.yml --profile umbra up -d umbra-bridge

# Or run directly:
cd services/umbra-bridge && pnpm install && pnpm start

# 2. Configure the bridge
export AUXIN_PRIVACY=umbra
export AUXIN_SOURCE=mock    # or twin, ros2
export HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=YOUR_KEY

# 3. (Optional) Generate a viewing key for your auditor
python scripts/setup_umbra_viewing_key.py --scope yearly --year 2026

# 4. Run the bridge
python sdk/scripts/run_bridge.py
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AUXIN_PRIVACY` | `direct` | Set to `umbra` to enable Umbra private payments |
| `UMBRA_SIDECAR_URL` | `http://localhost:3002` | Umbra sidecar base URL |
| `UMBRA_NETWORK` | `devnet` | Solana cluster for the sidecar (`devnet` or `mainnet`) |

## Fallback Behaviour

If the Umbra sidecar is unreachable or returns an error — ZK proof failure, Merkle tree
full, SDK error — the bridge automatically falls back to `DirectProvider` (public SOL
transfer) with a warning log:

```
umbra_provider.fallback_to_direct  error="connection refused"  lamports=5000
```

The bridge also performs a health check on startup.  If the sidecar is not running, a
warning is logged but the bridge starts anyway — payments will fall back to direct
until the sidecar becomes available.

## Dashboard

When a payment has `is_private=True`, the PaymentTicker shows:

- A **lock icon** (purple) instead of the SOL amount
- **"Private"** label instead of the amount value
- **"shielded recipient"** instead of the provider public key

This UI is identical across all privacy providers — `isPrivate=True` triggers the same
lock display regardless of whether Cloak, MagicBlock, or Umbra generated the payment.

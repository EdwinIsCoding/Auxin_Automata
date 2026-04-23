# Private Payments with MagicBlock Private Ephemeral Rollups

## What is MagicBlock PER?

[MagicBlock](https://magicblock.gg) provides **Private Ephemeral Rollups (PERs)** — high-performance
execution environments that run inside **Trusted Execution Environments (TEEs)**.  When SPL tokens are
delegated into the rollup, individual transfers happen privately within the TEE.  A crank periodically
settles balances back to Solana Mainnet with no traceable per-payment link on the public ledger.

Private Payments API base URL: `https://payments.magicblock.app`

## Why TEE-based Settlement Suits High-Frequency M2M Payments

Auxin Automata streams micro-payments from autonomous robot arms to compute providers every time the
Gemini safety oracle approves an action.  At 10 Hz telemetry with oracle gating, this can be
thousands of individual payment intents per hour.

### The Problem with Per-Payment On-Chain Transactions

Without a rollup:
- Each payment is a separate Solana transaction with a visible sender → receiver link.
- Payment frequency, amount, and recipient identity are readable by any blockchain observer.
- An observer can identify the compute provider, estimate operational throughput, detect business
  relationships, and front-run pricing negotiations.

### How MagicBlock PER Solves This

With `AUXIN_PRIVACY=magicblock`:

- **Pre-delegation**: The operator deposits a batch of wSOL into the MagicBlock rollup once
  (`delegate_budget()`).  This single on-chain tx puts funds into the TEE.
- **Private transfers**: Individual payments call `POST /v1/spl/transfer` with `privacy=private`.
  MagicBlock builds an unsigned transaction; the bridge signs and submits it.  Inside the TEE, the
  transfer settles immediately — no per-payment Solana block confirmation latency.
- **Settlement**: The crank periodically writes a settlement batch back to Solana.  The settlement
  reveals aggregate flows but not individual payment links.
- **Sub-second settlement inside the rollup**: TEE-native execution is not limited by Solana's 400ms
  block time.  Payment confirmation for the autonomous arm is immediate within the rollup.

### On-Chain Footprint Comparison

| Mode | Per-payment on-chain footprint |
|---|---|
| `direct` | One transaction per payment — sender, receiver, amount visible |
| `cloak` | One ZK deposit per payment — amount hidden, sender visible, receiver unlinkable |
| `magicblock` | **Zero per-payment transactions** — only batch settlement is visible |

## AML Compliance by Default

MagicBlock enforces compliance at the API layer via **Range** — a real-time AML and sanctions
screening service.  Every call to `POST /v1/spl/transfer` or `POST /v1/spl/deposit` is screened:

- **OFAC sanctions check**: IP geofencing and wallet address screening against OFAC SDN list.
- **Counterparty risk**: The destination wallet (compute provider) is screened on every payment.
- **Behavioural signals**: Unusual payment patterns trigger holds before execution.

Transactions failing AML checks are rejected with HTTP 400 before any on-chain action is taken.

### Why This Matters for the Submission Narrative

> "Every autonomous M2M payment from Auxin Automata is AML-screened without any additional
> infrastructure on the operator's side."

Operators do not run a compliance oracle.  MagicBlock's API enforces it.  The operator gets
AML coverage as a service, priced into the API access, with no extra integration cost.

This is the key differentiator from `cloak` (UTXO-based, no native AML screening) and `direct`
(no privacy, no AML screening beyond what Solana validators enforce).

### Compliance Architecture

```
Auxin Bridge._payment_worker
        │
        ▼  AUXIN_PRIVACY=magicblock
MagicBlockProvider.send_payment()
        │
        ├─▶ POST /v1/spl/transfer  ────▶  MagicBlock API
        │        │                              │
        │        │                         AML screening (Range)
        │        │                              │
        │        │                    ┌─── pass ─── reject (HTTP 400)
        │        ▼                    │
        │   unsigned tx ◀─────────────┘
        │        │
        ├─▶ sign with HardwareWallet keypair
        │        │
        └─▶ submit to Solana RPC
                 │
                 ▼
          TEE execution (private)
                 │
          crank settles batch to Solana (public, aggregate only)


Auxin Bridge._compliance_worker  ──▶  ALWAYS public chain (bypasses MagicBlock)
        │                                      │
        ▼                                      ▼
log_compliance() (AuxinProgramClient)   ComplianceLog PDA (immutable, on-chain)
```

**Key invariant:** Compliance events are **NEVER** routed through MagicBlockProvider.
Compliance hashes are public on-chain evidence; only M2M streaming payments are privatised.

## Enabling MagicBlock Payments

### Prerequisites

- Python 3.11+ with `auxin-sdk` installed
- A MagicBlock API key (contact MagicBlock for access — `MAGICBLOCK_API_KEY`)
- wSOL in the hardware wallet's ATA (required for pre-delegation)

### Setup

```bash
# 1. Configure environment
export AUXIN_PRIVACY=magicblock
export MAGICBLOCK_API_KEY=your_api_key_here
export MAGICBLOCK_CLUSTER=devnet          # or mainnet-beta
export AUXIN_SOURCE=mock                  # or twin, ros2
export HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=YOUR_KEY

# 2. Pre-delegate a compute budget (fund the rollup pool once)
python - <<'EOF'
import asyncio, os
from auxin_sdk.wallet import HardwareWallet
from auxin_sdk.privacy.magicblock import MagicBlockProvider

async def main():
    wallet = HardwareWallet.load_or_create("~/.config/auxin/hardware.json")
    provider = MagicBlockProvider(
        os.environ["HELIUS_RPC_URL"],
        api_key=os.environ.get("MAGICBLOCK_API_KEY"),
        cluster=os.environ.get("MAGICBLOCK_CLUSTER", "devnet"),
    )
    # Delegate 0.1 SOL (100_000_000 lamports) to the rollup
    sig = await provider.delegate_budget(wallet, lamports=100_000_000)
    print(f"Delegated: {sig}")

asyncio.run(main())
EOF

# 3. Run the bridge
python sdk/scripts/run_bridge.py
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AUXIN_PRIVACY` | `direct` | Set to `magicblock` to enable MagicBlock private payments |
| `MAGICBLOCK_API_URL` | `https://payments.magicblock.app` | MagicBlock API base URL |
| `MAGICBLOCK_API_KEY` | _(none)_ | API key for authenticated requests |
| `MAGICBLOCK_CLUSTER` | `devnet` | Solana cluster label (`devnet` or `mainnet-beta`) |

## Budget Pre-Delegation

Pre-delegation separates funding from payment execution:

```
delegate_budget(wallet, 100_000_000)   ← one on-chain tx
        │
        ▼
MagicBlock rollup holds 0.1 SOL
        │
        ├─▶ send_payment(lamports=5_000)   ← draws from pool, no on-chain tx per payment
        ├─▶ send_payment(lamports=5_000)
        ├─▶ send_payment(lamports=5_000)
        │   ... (thousands of micro-payments)
        │
        ▼
crank settles pool balance back to Solana (one batch tx)
```

### Trade-off

| Aspect | Pre-delegation |
|---|---|
| Speed | Fast — no per-payment deposit round-trip |
| Funds in TEE | Yes — batch amount held until consumed or withdrawn |
| Latency | Sub-second TEE settlement, then batch Solana commit |
| Recommendation | Set budget to ~1 hour of expected payment volume; top up periodically |

## Fallback Behaviour

If the MagicBlock API fails for any reason — network error, AML rejection, API outage — the bridge
automatically falls back to `DirectProvider` (public SOL transfer) with a warning log:

```
magicblock_provider.fallback_to_direct  error="connection refused"  lamports=5000
```

The demo never stalls on a privacy provider failure.

## Dashboard

When a payment has `is_private=True`, the PaymentTicker shows:

- A **lock icon** (purple) instead of the SOL amount
- **"Private"** label instead of the amount value
- **"shielded recipient"** instead of the provider public key
- The transaction signature and Explorer link are still shown (the settlement tx is public,
  but it reveals aggregate flows only — not the individual payment link)

This UI is identical to the Cloak mode — `isPrivate=True` triggers the same lock display
regardless of which privacy provider generated the payment.

## API Reference Summary

All endpoints are at `https://payments.magicblock.app`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/spl/deposit` | Deposit wSOL into the rollup (pre-delegation) |
| `POST` | `/v1/spl/transfer` | Private transfer within the rollup (per-payment) |
| `POST` | `/v1/spl/withdraw` | Withdraw from rollup back to Solana |
| `GET` | `/v1/spl/balance` | Query public balance for an account |
| `GET` | `/v1/spl/private-balance` | Query private balance inside the rollup |
| `GET` | `/health` | API health check |

All POST endpoints return an **unsigned serialized transaction** (`transactionBase64`).
The bridge signs it with the hardware wallet's keypair and submits it to Solana or the
rollup validator indicated by the response's `sendTo` field.

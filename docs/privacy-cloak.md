# Private Payments with Cloak

## What is Cloak?

[Cloak](https://www.cloakonchain.com/) is a privacy protocol on Solana that
uses a **UTXO-based shield pool** with Groth16 ZK proofs and Merkle tree
commitments.  When SOL is deposited into the pool, it becomes an unlinkable
UTXO commitment — the on-chain record reveals that *someone* deposited
*some amount*, but not *who* the intended recipient is or *what* the payment
pattern looks like over time.

Recipients detect their incoming payments using a **viewing key** and withdraw
through Cloak's **relay service**, which submits the withdrawal transaction so
the recipient's address never appears as the direct counterparty of the sender.

Program ID (mainnet & devnet): `zh1eLd6rSphLejbFfJEneUwzHRfMKxgzrgkfwA6qRkW`

## Why Autonomous Hardware Needs Private Payments

Auxin Automata streams micro-payments from autonomous hardware (robot arms) to
compute providers every time the Gemini safety oracle approves an action.  These
payments happen at machine frequency — potentially thousands per day.

Without privacy, this payment stream is **competitive intelligence on a public
ledger**.  An observer can:

- **Identify the compute provider** by following the payment destination.
- **Estimate operational throughput** by counting payment frequency.
- **Detect business relationships** between hardware operators and providers.
- **Front-run pricing negotiations** by observing payment amounts.

Cloak eliminates this leakage.  With `AUXIN_PRIVACY=cloak`:

- Each payment deposits into the shield pool as an **unlinkable UTXO**.
- The provider detects payments via their **viewing key** and batch-withdraws.
- On-chain, there is no visible link between the hardware wallet and the provider.
- Payment amounts and timing are hidden from public observers.

## Enabling Cloak Payments

### Prerequisites

- Node.js >= 20 (for the `@cloak.dev/sdk` bridge)
- pnpm (for installing the bridge dependencies)

### Setup

```bash
# 1. Install the Cloak bridge dependencies
cd sdk/src/auxin_sdk/privacy/cloak_bridge
pnpm install
cd -

# 2. Generate the provider's Cloak identity (one-time)
python scripts/setup_cloak_provider.py \
  --output ~/.config/auxin/cloak_provider.json

# 3. Configure the bridge environment
export AUXIN_PRIVACY=cloak
export AUXIN_SOURCE=mock        # or twin, ros2
export HELIUS_RPC_URL=https://devnet.helius-rpc.com/?api-key=YOUR_KEY

# 4. Run the bridge
python sdk/scripts/run_bridge.py
```

### Environment Variables

| Variable           | Default                                          | Description |
|--------------------|--------------------------------------------------|-------------|
| `AUXIN_PRIVACY`    | `direct`                                         | Set to `cloak` to enable private payments |
| `CLOAK_PROGRAM_ID` | `zh1eLd6rSphLejbFfJEneUwzHRfMKxgzrgkfwA6qRkW`  | Cloak program address |
| `CLOAK_RELAY_URL`  | SDK default                                      | Cloak relay service URL |

## How Viewing Keys Work

Cloak's viewing key system provides **selective disclosure** — the ability to
prove payment history to an authorised auditor without making it public.

### Key Hierarchy

```
UTXO Private Key  (SECRET — allows withdrawal)
    │
    ├── Nullifier Key (nk)
    │       │
    │       └── Viewing Key  (SAFE TO SHARE with auditors)
    │               │
    │               └── Can scan the Merkle tree to detect
    │                   which UTXOs belong to this identity
    │
    └── UTXO Public Key  (commitment identity, on-chain)
```

### For Operators

When you run `setup_cloak_provider.py`, it generates:

- **UTXO private key** — stored in `~/.config/auxin/cloak_provider.json`.
  This is equivalent to a wallet private key.  **Keep it secret.**
- **Viewing key** — derived from the private key.  Share this with your
  compliance auditor.  It allows them to verify payments but NOT withdraw.

### For Auditors

With the viewing key, an auditor can:

1. **Verify every payment** — amount, timestamp, UTXO commitment.
2. **Confirm payments match the compliance record** — cross-reference with
   the public compliance hashes logged via `log_compliance()`.
3. **Cannot withdraw funds** — the viewing key is read-only.
4. **Cannot forge payments** — the viewing key cannot create new UTXOs.

## Compliance Architecture

Auxin Automata has a strict separation between compliance and payments:

```
                    ┌─────────────────────────────────────────┐
                    │           Bridge._payment_worker        │
                    │                                         │
  Normal frames ──▶ │  oracle.check() ──▶ privacy_provider   │
                    │                     .send_payment()     │
                    │                         │               │
                    │       ┌─────────────────┼───────────────┤
                    │       │  AUXIN_PRIVACY=  │               │
                    │       │  direct │ cloak  │               │
                    │       │    ▼    │   ▼    │               │
                    │       │ public  │ shield │               │
                    │       │ SOL tx  │ pool   │               │
                    └───────┴─────────┴────────┘               │
                                                               │
                    ┌─────────────────────────────────────────┐
                    │       Bridge._compliance_worker         │
                    │                                         │
  Anomaly frames ──▶│  _submission.log_compliance()           │
                    │       │                                 │
                    │       ▼  ALWAYS public chain            │
                    │  ComplianceLog PDA (immutable)          │
                    └─────────────────────────────────────────┘
```

**Key invariant:** Compliance events are NEVER routed through any privacy
provider.  This is enforced in `bridge.py` and tested in
`test_cloak_provider.py::TestComplianceBypassesCloakProvider`.

The rationale:

- **Compliance hashes are public on-chain evidence.**  They prove that the
  system detected and recorded every safety anomaly.  Hiding them would
  defeat their purpose.
- **Payment details are private but auditable.**  An operator's competitive
  information (who they pay, how often, how much) is shielded from public
  observers.  But an auditor with the viewing key can verify the full record.

This gives the operator **privacy from competitors** while maintaining **full
accountability to regulators**.

## Fallback Behaviour

If the Cloak integration fails for any reason — Node.js not installed, SDK
error, relay service down, ZK proof timeout — the bridge automatically falls
back to `DirectProvider` (public SOL transfer) with a warning log:

```
cloak_provider.fallback_to_direct  error="relayer unreachable"  lamports=5000
```

The demo never stalls on a privacy provider failure.  This fallback is
configured automatically when `AUXIN_PRIVACY=cloak` is set in `run_bridge.py`.

## Dashboard

When a payment has `is_private=True`, the dashboard PaymentTicker shows:

- A **lock icon** (purple) instead of the SOL amount
- **"Private"** label instead of the amount value
- **"shielded recipient"** instead of the provider public key
- The transaction signature and Explorer link are still shown (the deposit
  tx is public, but it doesn't reveal the recipient)

## Technical Implementation

The Cloak SDK (`@cloak.dev/sdk`) is TypeScript only.  The Python
`CloakProvider` calls a Node.js subprocess bridge:

```
CloakProvider.send_payment()
    │
    ▼
asyncio.create_subprocess_exec("node", "deposit.mjs")
    │
    ├── stdin:  JSON { rpc_url, wallet_secret_b64, amount_lamports, ... }
    │
    ├── @cloak.dev/sdk:
    │     generateUtxoKeypair()
    │     createUtxo(amount, keypair)
    │     transact({ deposit into shield pool })
    │
    └── stdout: JSON { signature, utxo_commitment, utxo_private_key_hex }
```

The bridge scripts live at `sdk/src/auxin_sdk/privacy/cloak_bridge/`.

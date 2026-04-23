# Payment Privacy for Autonomous Hardware

## Why Autonomous Hardware Needs Payment Privacy

**Operational intelligence leakage.** Every micropayment a robot arm makes is a data point.
At machine frequency — thousands of payments per day — the public ledger becomes a
high-resolution operational log that any competitor can read.  An observer watching a fleet
of arms can see which compute provider each arm uses, how often each arm runs inference (and
therefore how heavily it is utilised), and how much each operator pays per inference cycle.
Over weeks, this yields a near-complete picture of a competitor's cost structure, throughput,
and operational patterns — extracted from public blockchain data with no hacking required.

**Competitive exposure in M2M markets.** Unlike human payments — occasional, varied, and
hard to aggregate — machine-to-machine micropayments are regular, predictable, and
high-volume.  A robot paying the same provider every 100ms for eight hours a day produces
~288,000 on-chain transactions per day.  Each transaction confirms the business relationship,
the payment rate, and the operational window.  In a market where AI compute pricing is
competitively sensitive, this is the equivalent of publishing your supplier contract on a
public billboard.  Payment privacy removes the data without removing the economic activity.

**The compliance paradox.** Operators face a genuine tension: regulators and auditors need
evidence that safety anomalies were detected and logged; competitors and adversaries should
not be able to read the operational pattern of every action the machine takes.  Auxin Automata
resolves this by maintaining a strict separation between the economic layer and the safety
layer.  Compliance logs — SHA-256 hashes of raw telemetry frames, severity, and reason codes
— go to immutable on-chain PDAs on every anomaly, always public, never rate-limited.
Payment details — provider identity, frequency, amount — can be privatised through any of the
supported privacy providers without affecting the compliance record.

---

## Privacy Provider Comparison

| | Cloak | MagicBlock | Umbra |
|---|---|---|---|
| **Privacy model** | ZK UTXO shield pool | TEE-based ephemeral rollup | Unified Merkle mixer pool |
| **On-chain footprint per payment** | One ZK deposit tx (sender visible, receiver unlinkable) | Zero (only batch settlement visible) | One Merkle leaf (deposit unlinkable from withdrawal) |
| **Compliance mechanism** | Viewing key — auditor derives read access from UTXO private key hierarchy | AML screening (Range) on every API call; TEE attestation | Time-scoped Transaction Viewing Keys (TVKs) derived from Master Viewing Key |
| **AML screening** | Operator-side | **API-layer (automatic, no infra)** | Operator-side via viewing key disclosure |
| **Settlement latency** | Per-payment (ZK proof ~1–5s) | Sub-second inside TEE; batch Solana commit | Per-payment (ZK proof ~1–5s); mixing delay before withdrawal |
| **Anonymity source** | Sender-receiver link broken by shield pool | No per-payment on-chain record; batch settlement only | Deposit and withdrawal unlinkable; anonymity grows with pool size |
| **Setup** | Node ≥20 + `pnpm install` in `cloak_bridge/` | `MAGICBLOCK_API_KEY` + REST calls | Umbra sidecar (`docker-compose --profile umbra`) |
| **Program (devnet)** | `zh1eLd6rSphLejbFfJEneUwzHRfMKxgzrgkfwA6qRkW` | REST API (`payments.magicblock.app`) | `DSuKkyqGVGgo4QtPABfxKJKygUDACbUhirnuv63mEpAJ` |
| **Python impl** | `sdk/src/auxin_sdk/privacy/cloak.py` | `sdk/src/auxin_sdk/privacy/magicblock.py` | `sdk/src/auxin_sdk/privacy/umbra.py` |
| **Docs** | [`privacy-cloak.md`](privacy-cloak.md) | [`privacy-magicblock.md`](privacy-magicblock.md) | [`privacy-umbra.md`](privacy-umbra.md) |

### Choosing a Provider

- **Prefer `magicblock`** when AML compliance coverage matters and sub-second settlement
  is needed.  Zero per-payment on-chain footprint is the strongest operational-pattern
  hiding of the three.

- **Prefer `umbra`** when the anonymity set matters (pool grows with all users, not just
  yours) and auditor-side selective disclosure is required.  Time-scoped TVKs give
  regulators exactly the window they need, no more.

- **Prefer `cloak`** for a clean cryptographic guarantee with auditor viewing keys and a
  minimal infrastructure footprint (Node.js subprocess, no sidecar, no API key).

- **Use `direct`** for development, CI, and any context where operational transparency is
  acceptable or required.

---

## Compliance Architecture

Compliance events exist to prove that every safety anomaly was detected and recorded.  Making
that record private would defeat its purpose.  This constraint is architectural — not just
a policy choice — and is enforced in three places:

### 1. Bridge (`bridge.py`)

`_payment_worker` calls `privacy_provider.send_payment()`.
`_compliance_worker` calls `program_client.log_compliance()` directly.
There is no code path that routes a compliance event through any `PrivacyProvider`.

```
Bridge._payment_worker
    └─▶ privacy_provider.send_payment()  ← AUXIN_PRIVACY controls this
            └─▶ CloakProvider | MagicBlockProvider | UmbraProvider | DirectProvider
                    └─▶ Solana tx (private or public depending on provider)

Bridge._compliance_worker
    └─▶ program_client.log_compliance()  ← ALWAYS this, no exception
            └─▶ log_compliance_event instruction
                    └─▶ ComplianceLog PDA (immutable, public on-chain)
```

### 2. Separate queue

The compliance queue is unbounded and never rate-limited.  The payment queue is bounded
and can be throttled.  A saturated payment path cannot delay a compliance event.

### 3. Tests

`TestComplianceBypassesCloakProvider`, `TestComplianceBypassesMagicBlockProvider`,
and `TestComplianceBypassesUmbraProvider` each verify this invariant by asserting that
`privacy_provider.send_payment` is never called when a compliance task is processed.

---

## PrivacyProvider ABC

All four providers implement a single interface:

```python
class PrivacyProvider(ABC):
    @abstractmethod
    async def send_payment(
        self,
        wallet: HardwareWallet,
        owner_pubkey: Any,
        provider_pubkey: Any,
        lamports: int,
        *,
        idempotency_key: str,
    ) -> PaymentResult: ...
```

`PaymentResult` carries `tx_signature`, `privacy_provider` (string label), `is_private`
(bool), `confirmation_slot`, and `metadata` (provider-specific dict).

The bridge passes `result.is_private` and `result.privacy_provider` to the WebSocket
broadcast, which the dashboard uses to render the lock icon in `PaymentTicker`.

Swapping providers requires one environment variable change.  Zero code changes.
This is the payment-privacy equivalent of the `AUXIN_SOURCE` hardware-agnosticism contract.

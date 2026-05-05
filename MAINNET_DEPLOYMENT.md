# Mainnet Deployment Record

## Program IDs

| Cluster | Program ID | Status |
|---|---|---|
| **Mainnet** | `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm` | Live (May 2026) |
| **Devnet**  | `7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm` | Live (April 2026) |

## Mainnet Wallets

| Wallet | Public Key | Purpose |
|---|---|---|
| Hardware | `trPhnio8TMxUCo6bRC25cyyo2htEGJmNLDcgzDizeq9` | Signs compute payments and compliance logs |
| Provider | `BmvFq4CwWHbhwXZdhJhTLqb6RBNZgNgG34JNaRQ6Ef2U` | Receives streaming payments |
| Owner    | `3ETZinXZQfVvYcq9cDWsM5zcaWMwzU9FGQsA7ByTEW9h` | Authority over agent PDA |
| Agent PDA | `BJ7w5ZEsUvDb76XboHUC7Dnqyofjmi5fnP6uNvaKj48m` | On-chain agent account |
| Provider PDA | `91ta2s4i2sFUJc1Eyd3MHEq9acfYJxe53ry3b6zk83i4` | Whitelist entry |

## Deployment Date

`2026-05-05T02:21:30Z` — slot 417657493
Deploy tx: `5wVJATiLnug7r2BaD5DpxqkcYwum644cjKK5aa8EKDhu6yyY5fzV8NW5QtrRKSmcy46UyqCQFDfZxZsGQ2DwfTkC`

## Verify on Solana Explorer

**Mainnet program:**
```
https://explorer.solana.com/address/<MAINNET_PROGRAM_ID>
```

**Devnet program:**
```
https://explorer.solana.com/address/7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm?cluster=devnet
```

## Deployment Files

| File | Purpose | Committed? |
|---|---|---|
| `programs/deployed.json` | Devnet program record (source of truth for CI) | Yes |
| `programs/deployed_devnet.json` | Safety backup of devnet record | Yes |
| `programs/deployed_mainnet.json` | Mainnet program record | Yes |
| `sdk/.env.devnet` | Devnet runtime config | No (gitignored) |
| `sdk/.env.mainnet` | Mainnet runtime config (real keys) | No (gitignored) |
| `sdk/.env.mainnet.example` | Mainnet config template | Yes |

## Switching Between Clusters

The SAME codebase, binary, and SDK runs on both clusters. The ONLY difference is one env var:

```bash
# Run bridge on Devnet (default — safe, uses free airdrops)
AUXIN_CLUSTER=devnet uv run python sdk/scripts/run_bridge.py

# Run bridge on Mainnet (production — real SOL)
AUXIN_CLUSTER=mainnet uv run python sdk/scripts/run_bridge.py
```

Dashboard (Next.js):
```bash
# Devnet (local dev)
pnpm dev   # loads dashboard/.env.development automatically

# Mainnet (production build)
pnpm build && pnpm start   # loads dashboard/.env.production
```

## CI / GitHub Actions Rule

CI **only** ever touches Devnet. Mainnet is manual-only.
The `AUXIN_CLUSTER` variable is never set to `mainnet` in any CI workflow.

## Deployment Scripts

| Script | Purpose |
|---|---|
| `scripts/deploy_mainnet.sh` | Deploy Anchor program to mainnet (idempotent, restores CLI config on exit) |
| `scripts/initialise_mainnet.py` | Generate mainnet keypairs, fund wallets, init PDAs, smoke test |
| `scripts/deploy_devnet.sh` | Deploy to Devnet (existing, CI-driven) |
| `scripts/setup_devnet.py` | Init Devnet keypairs and PDAs (existing) |

## Cost Summary

| Item | SOL | USD (approx) | Recurring? |
|---|---|---|---|
| Program deployment rent | 1.5–3 | $200–450 | One-time (deposit, recoverable) |
| IDL account rent | 0.05 | $7 | One-time |
| Hardware wallet funding | 0.5 | $75 | Top up as needed |
| Provider wallet funding | 0.01 | $1.50 | One-time |
| PDA initialization | 0.003 | $0.50 | One-time |
| Smoke test transactions | ~0.001 | $0.15 | One-time |

Rent is a **deposit**, not a fee. Closing the program account recovers the SOL.

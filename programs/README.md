# /programs — agentic_hardware_bridge

Anchor 0.30+ workspace for the Auxin Automata Solana program.

## Status

**Phase 0:** Directory scaffold only. The Anchor workspace is initialised in Phase 2A.

Phase 2A will create:
- `Anchor.toml`, `Cargo.toml`, `programs/agentic_hardware_bridge/`
- Instructions: `initialize_agent`, `stream_compute_payment`, `log_compliance_event`, `update_provider_whitelist`
- Accounts: `HardwareAgent`, `ComputeProvider`, `ComplianceLog`
- TypeScript test suite

## Prerequisites

- Rust stable
- Solana CLI 1.18+
- Anchor 0.30+ (`avm install 0.30.1 && avm use 0.30.1`)

## Commands (available after Phase 2A)

```bash
anchor build
anchor test          # localnet
anchor deploy        # devnet via scripts/deploy_devnet.sh
```

## Environment

Copy `.env.example` to `.env` and fill in `HELIUS_RPC_URL` and `DEPLOYER_KEYPAIR_PATH`.

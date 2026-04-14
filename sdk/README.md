# auxin-sdk

Python SDK for Auxin Automata — hardware wallets, telemetry schema, Gemini oracle, and Solana bridge.

See the [root README](../README.md) and [CLAUDE.md](../CLAUDE.md) for architecture context.

## Install

```bash
uv sync
```

## Test

```bash
uv run pytest --cov=auxin_sdk --cov-fail-under=80
# With Devnet integration tests:
uv run pytest --run-network
```

## Structure

```
src/auxin_sdk/
  wallet.py        HardwareWallet (solders Keypair + async RPC)
  schema.py        TelemetryFrame (Pydantic v2)
  hashing.py       canonical_json + sha256_hex
  sources/base.py  TelemetrySource ABC (agnosticism contract)
  logging.py       configure_structlog + bind_request_id
```

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy_devnet.sh — Idempotent Devnet deploy for agentic_hardware_bridge
#
# Required env vars:
#   HELIUS_RPC_URL          Helius Devnet RPC endpoint
#   DEPLOYER_KEYPAIR_PATH   Path to deployer keypair JSON (default: ~/.config/solana/id.json)
#
# Optional flags:
#   --force   Force redeploy even if a deployed.json already exists
#
# Writes: /programs/deployed.json  { program_id, cluster, idl_authority, deployed_at }
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROGRAMS_DIR="$REPO_ROOT/programs"
DEPLOYED_JSON="$PROGRAMS_DIR/deployed.json"

# ── Defaults ──────────────────────────────────────────────────────────────────
: "${HELIUS_RPC_URL:?'HELIUS_RPC_URL is required'}"
: "${DEPLOYER_KEYPAIR_PATH:="${HOME}/.config/solana/id.json"}"
FORCE=false

# ── Arg parsing ───────────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --force) FORCE=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ── Idempotency guard ─────────────────────────────────────────────────────────
if [[ -f "$DEPLOYED_JSON" && "$FORCE" == "false" ]]; then
  EXISTING_ID=$(python3 -c "import json,sys; d=json.load(open('$DEPLOYED_JSON')); print(d['program_id'])")
  echo "✓ Already deployed: $EXISTING_ID"
  echo "  Run with --force to redeploy."
  exit 0
fi

# ── Prerequisite checks ───────────────────────────────────────────────────────
command -v anchor >/dev/null 2>&1 || { echo "anchor not found in PATH"; exit 1; }
command -v solana >/dev/null 2>&1 || { echo "solana not found in PATH"; exit 1; }
[[ -f "$DEPLOYER_KEYPAIR_PATH" ]] || { echo "Keypair not found: $DEPLOYER_KEYPAIR_PATH"; exit 1; }

echo "────────────────────────────────────────────────────────────────────────"
echo " Auxin Automata — Devnet deploy"
echo " RPC : $HELIUS_RPC_URL"
echo " Key : $DEPLOYER_KEYPAIR_PATH"
echo "────────────────────────────────────────────────────────────────────────"

# ── Confirm deployer balance ──────────────────────────────────────────────────
BALANCE=$(solana balance "$DEPLOYER_KEYPAIR_PATH" --url "$HELIUS_RPC_URL" 2>&1)
echo "Deployer balance: $BALANCE"

# ── Build ─────────────────────────────────────────────────────────────────────
echo ""
echo "▶ Building program..."
cd "$PROGRAMS_DIR"
anchor build

# ── Sync program ID ───────────────────────────────────────────────────────────
echo ""
echo "▶ Syncing program ID..."
anchor keys sync

# ── Deploy ────────────────────────────────────────────────────────────────────
echo ""
echo "▶ Deploying to Devnet..."
anchor deploy \
  --provider.cluster "$HELIUS_RPC_URL" \
  --provider.wallet "$DEPLOYER_KEYPAIR_PATH"

# ── Extract deployed program ID ───────────────────────────────────────────────
PROGRAM_ID=$(anchor keys list 2>&1 | grep "agentic_hardware_bridge" | awk '{print $NF}')
echo ""
echo "▶ Program ID: $PROGRAM_ID"

# ── Upload IDL ────────────────────────────────────────────────────────────────
echo ""
echo "▶ Uploading IDL to Devnet..."
IDL_PATH="$PROGRAMS_DIR/target/idl/agentic_hardware_bridge.json"
if [[ -f "$IDL_PATH" ]]; then
  anchor idl init \
    --filepath "$IDL_PATH" \
    --provider.cluster "$HELIUS_RPC_URL" \
    --provider.wallet "$DEPLOYER_KEYPAIR_PATH" \
    "$PROGRAM_ID" 2>/dev/null \
  || anchor idl upgrade \
    --filepath "$IDL_PATH" \
    --provider.cluster "$HELIUS_RPC_URL" \
    --provider.wallet "$DEPLOYER_KEYPAIR_PATH" \
    "$PROGRAM_ID"
  echo "✓ IDL uploaded"
else
  echo "⚠ IDL not found at $IDL_PATH — skipping IDL upload"
fi

# ── Write deployed.json ───────────────────────────────────────────────────────
DEPLOYER_PUBKEY=$(solana-keygen pubkey "$DEPLOYER_KEYPAIR_PATH")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

python3 - <<PYEOF
import json, sys

data = {
    "program_id":    "$PROGRAM_ID",
    "cluster":       "devnet",
    "rpc_url":       "$HELIUS_RPC_URL",
    "idl_authority": "$DEPLOYER_PUBKEY",
    "deployed_at":   "$TIMESTAMP",
}
with open("$DEPLOYED_JSON", "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print(json.dumps(data, indent=2))
PYEOF

echo ""
echo "────────────────────────────────────────────────────────────────────────"
echo " ✓ Deploy complete"
echo " Explorer: https://explorer.solana.com/address/$PROGRAM_ID?cluster=devnet"
echo "────────────────────────────────────────────────────────────────────────"

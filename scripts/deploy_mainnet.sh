#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy_mainnet.sh — Deploy agentic_hardware_bridge to Solana MAINNET
#
# CRITICAL: The Devnet deployment is NEVER touched by this script.
# Devnet program ID: 7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm
#
# Required env vars:
#   MAINNET_RPC_URL         Helius (or other) mainnet RPC — must be HTTP, not WSS
#   DEPLOYER_KEYPAIR_PATH   Path to funded deployer keypair JSON (>= 3 SOL)
#
# Optional flags:
#   --force   Force redeploy even if deployed_mainnet.json already exists
#
# Writes:
#   programs/deployed_mainnet.json  { program_id, cluster, deployer, deployed_at }
#   programs/deployed_devnet.json   copy of programs/deployed.json (safety backup)
#
# Cost: ~1.5–3 SOL rent deposit (recoverable if program is ever closed)
#       + ~0.001 SOL for the IDL account
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROGRAMS_DIR="$REPO_ROOT/programs"
DEPLOYED_MAINNET_JSON="$PROGRAMS_DIR/deployed_mainnet.json"
DEPLOYED_DEVNET_JSON="$PROGRAMS_DIR/deployed_devnet.json"
DEPLOYED_JSON="$PROGRAMS_DIR/deployed.json"  # existing devnet deployment — READ ONLY

# ── Env vars ──────────────────────────────────────────────────────────────────
: "${MAINNET_RPC_URL:?'MAINNET_RPC_URL is required (e.g. https://mainnet.helius-rpc.com/?api-key=KEY)'}"
: "${DEPLOYER_KEYPAIR_PATH:="${HOME}/.config/solana/id.json"}"

FORCE=false
for arg in "$@"; do
  case $arg in
    --force) FORCE=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ── Safety banner ─────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  *** MAINNET DEPLOYMENT — REAL SOL WILL BE SPENT ***"
echo "  Devnet deployment is untouched and will remain running."
echo "  Devnet program ID: 7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# ── Idempotency guard ─────────────────────────────────────────────────────────
if [[ -f "$DEPLOYED_MAINNET_JSON" && "$FORCE" == "false" ]]; then
  EXISTING_ID=$(python3 -c "import json; d=json.load(open('$DEPLOYED_MAINNET_JSON')); print(d['program_id'])")
  echo "✓ Mainnet already deployed: $EXISTING_ID"
  echo "  Explorer: https://explorer.solana.com/address/$EXISTING_ID"
  echo "  Run with --force to redeploy."
  exit 0
fi

# ── Prerequisite checks ───────────────────────────────────────────────────────
command -v anchor >/dev/null 2>&1   || { echo "ERROR: anchor not found in PATH"; exit 1; }
command -v solana >/dev/null 2>&1   || { echo "ERROR: solana not found in PATH"; exit 1; }
command -v python3 >/dev/null 2>&1  || { echo "ERROR: python3 not found in PATH"; exit 1; }
[[ -f "$DEPLOYER_KEYPAIR_PATH" ]]   || { echo "ERROR: Keypair not found: $DEPLOYER_KEYPAIR_PATH"; exit 1; }

# ── Preserve the Devnet deployment record (safety backup) ─────────────────────
if [[ -f "$DEPLOYED_JSON" && ! -f "$DEPLOYED_DEVNET_JSON" ]]; then
  cp "$DEPLOYED_JSON" "$DEPLOYED_DEVNET_JSON"
  echo "✓ Preserved Devnet deployment record → $DEPLOYED_DEVNET_JSON"
fi

# ── Save current Solana CLI config so we can restore it ──────────────────────
ORIGINAL_CLUSTER=$(solana config get | grep "RPC URL" | awk '{print $NF}' || echo "https://api.devnet.solana.com")
ORIGINAL_KEYPAIR=$(solana config get | grep "Keypair Path" | awk '{print $NF}' || echo "$HOME/.config/solana/id.json")

_restore_config() {
  echo ""
  echo "▶ Restoring Solana CLI config to devnet..."
  solana config set --url "$ORIGINAL_CLUSTER" --keypair "$ORIGINAL_KEYPAIR" >/dev/null 2>&1 || true
  echo "  ✓ Restored (RPC: $ORIGINAL_CLUSTER)"
}

# Restore config on exit — even on failure
trap _restore_config EXIT

# ── Check deployer balance ────────────────────────────────────────────────────
echo "▶ Checking deployer balance on mainnet..."
RAW_BALANCE=$(solana balance "$DEPLOYER_KEYPAIR_PATH" --url "$MAINNET_RPC_URL" 2>&1)
echo "  Balance: $RAW_BALANCE"

# Extract the numeric part (e.g. "3.512 SOL" → "3.512")
BALANCE_SOL=$(echo "$RAW_BALANCE" | grep -oE '[0-9]+\.[0-9]+' | head -1 || echo "0")

# Compare as integer milliSOL to avoid bash floating point
BALANCE_MSOL=$(python3 -c "print(int(float('$BALANCE_SOL') * 1000))")
MIN_MSOL=2200  # 2.2 SOL minimum (actual cost ~2.07 SOL, see MAINNET_DEPLOYMENT.md)

if [[ "$BALANCE_MSOL" -lt "$MIN_MSOL" ]]; then
  echo ""
  echo "ERROR: Insufficient SOL for mainnet deployment."
  echo "  Need:  at least 2.2 SOL (program rent ~1.55 + wallets 0.51 + fees + buffer)"
  echo "  Have:  $BALANCE_SOL SOL"
  echo ""
  echo "  → Swap more USDG to SOL on jup.ag, then re-run this script."
  exit 1
fi
echo "  ✓ Balance sufficient ($BALANCE_SOL SOL)"

# ── Set Solana CLI to mainnet for deployment ──────────────────────────────────
echo ""
echo "▶ Switching Solana CLI to mainnet..."
solana config set --url "$MAINNET_RPC_URL" --keypair "$DEPLOYER_KEYPAIR_PATH" >/dev/null
echo "  ✓ CLI now pointing at mainnet"

# ── Build ─────────────────────────────────────────────────────────────────────
echo ""
echo "▶ Building Anchor program..."
cd "$PROGRAMS_DIR"
anchor build
echo "  ✓ Build complete"

# ── Deploy to mainnet ─────────────────────────────────────────────────────────
echo ""
echo "▶ Deploying to mainnet..."
echo "  (This may take 1–3 minutes. Real SOL is being spent.)"
echo ""

# Use a dedicated mainnet program keypair if one exists; otherwise let Anchor
# generate a new keypair. The resulting program ID is different from Devnet.
MAINNET_PROGRAM_KEYPAIR="$HOME/.config/auxin/program_mainnet.json"

if [[ -f "$MAINNET_PROGRAM_KEYPAIR" ]]; then
  DEPLOY_EXTRA="--program-keypair $MAINNET_PROGRAM_KEYPAIR"
  echo "  Using existing mainnet program keypair: $MAINNET_PROGRAM_KEYPAIR"
else
  DEPLOY_EXTRA=""
  echo "  No existing mainnet program keypair — Anchor will generate one."
fi

anchor deploy \
  --provider.cluster "$MAINNET_RPC_URL" \
  --provider.wallet "$DEPLOYER_KEYPAIR_PATH" \
  $DEPLOY_EXTRA

# ── Extract new mainnet program ID ───────────────────────────────────────────
# anchor keys list shows the program ID from the most recent build/deploy keypair
PROGRAM_ID=$(anchor keys list 2>&1 | grep "agentic_hardware_bridge" | awk '{print $NF}')

if [[ -z "$PROGRAM_ID" ]]; then
  echo ""
  echo "ERROR: Could not determine program ID from anchor keys list."
  echo "  Check the anchor deploy output above for the deployed program address."
  exit 1
fi

echo ""
echo "  ✓ Mainnet program deployed: $PROGRAM_ID"

# ── Upload IDL to mainnet ─────────────────────────────────────────────────────
echo ""
echo "▶ Uploading IDL to mainnet..."
IDL_PATH="$PROGRAMS_DIR/target/idl/agentic_hardware_bridge.json"
if [[ -f "$IDL_PATH" ]]; then
  anchor idl init \
    --filepath "$IDL_PATH" \
    --provider.cluster "$MAINNET_RPC_URL" \
    --provider.wallet "$DEPLOYER_KEYPAIR_PATH" \
    "$PROGRAM_ID" 2>/dev/null \
  || anchor idl upgrade \
    --filepath "$IDL_PATH" \
    --provider.cluster "$MAINNET_RPC_URL" \
    --provider.wallet "$DEPLOYER_KEYPAIR_PATH" \
    "$PROGRAM_ID"
  echo "  ✓ IDL uploaded"
else
  echo "  ⚠ IDL not found at $IDL_PATH — skipping (run anchor build first)"
fi

# ── Write deployed_mainnet.json ───────────────────────────────────────────────
DEPLOYER_PUBKEY=$(solana-keygen pubkey "$DEPLOYER_KEYPAIR_PATH")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

python3 - <<PYEOF
import json

data = {
    "program_id":  "$PROGRAM_ID",
    "cluster":     "mainnet",
    "rpc_url":     "$MAINNET_RPC_URL",
    "deployer":    "$DEPLOYER_PUBKEY",
    "deployed_at": "$TIMESTAMP",
}
with open("$DEPLOYED_MAINNET_JSON", "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("  Wrote: $DEPLOYED_MAINNET_JSON")
PYEOF

# ── Confirm Devnet record is intact ──────────────────────────────────────────
DEVNET_ID=$(python3 -c "import json; d=json.load(open('$DEPLOYED_JSON')); print(d['program_id'])")
echo ""
echo "  ✓ Devnet program ID unchanged: $DEVNET_ID"

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "  ✓ Mainnet deployment complete"
echo ""
echo "  Mainnet program : $PROGRAM_ID"
echo "  Explorer        : https://explorer.solana.com/address/$PROGRAM_ID"
echo "  Devnet program  : $DEVNET_ID  (untouched)"
echo ""
echo "  Next steps:"
echo "    1. Copy sdk/.env.mainnet.example → sdk/.env.mainnet"
echo "    2. Set PROGRAM_ID=$PROGRAM_ID in sdk/.env.mainnet"
echo "    3. Run: python scripts/initialise_mainnet.py"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# _restore_config runs automatically via trap EXIT

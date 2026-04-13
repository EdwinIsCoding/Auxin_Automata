#!/usr/bin/env bash
# Install tools not covered by devcontainer features:
# Solana CLI, Anchor (via avm), uv, pnpm.
set -euo pipefail

SOLANA_VERSION="1.18.26"
ANCHOR_VERSION="0.30.1"
PNPM_VERSION="9"

echo ">>> Installing Solana CLI ${SOLANA_VERSION}"
sh -c "$(curl -sSfL "https://release.solana.com/v${SOLANA_VERSION}/install")"
SOLANA_BIN="$HOME/.local/share/solana/install/active_release/bin"
export PATH="$SOLANA_BIN:$PATH"
echo "export PATH=\"${SOLANA_BIN}:\$PATH\"" >> "$HOME/.bashrc"
solana --version

echo ">>> Installing Anchor ${ANCHOR_VERSION} via avm"
cargo install --git https://github.com/coral-xyz/anchor avm --locked --force
avm install "${ANCHOR_VERSION}"
avm use "${ANCHOR_VERSION}"
anchor --version

echo ">>> Installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"
uv --version

echo ">>> Installing pnpm ${PNPM_VERSION}"
npm install -g "pnpm@${PNPM_VERSION}"
pnpm --version

echo ">>> All tools installed successfully."

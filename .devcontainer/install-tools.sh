#!/bin/bash
set -e

echo "Installing Solana CLI..."
sh -c "$(curl -sSfL https://release.solana.com/v1.18.11/install)"
export PATH="/root/.local/share/solana/install/active_release/bin:$PATH"

echo "Installing Anchor version manager (AVM)..."
cargo install --git https://github.com/coral-xyz/anchor avm --locked --force

echo "Installing Anchor 0.30.0..."
avm install 0.30.0
avm use 0.30.0

echo "Installing uv (Python package manager)..."
curl -LsSf https://astral.sh/uv/install.sh | sh

echo "Tools installed successfully!"

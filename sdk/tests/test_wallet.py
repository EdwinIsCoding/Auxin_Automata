"""Tests for auxin_sdk.wallet.HardwareWallet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from solders.keypair import Keypair

from auxin_sdk.wallet import HardwareWallet

# ── Keypair persistence ───────────────────────────────────────────────────────


def test_load_or_create_new_keypair(tmp_path: Path) -> None:
    """Creating a wallet at a non-existent path writes a 64-byte keypair JSON."""
    keypair_path = tmp_path / "hardware.json"

    wallet = HardwareWallet.load_or_create(keypair_path)

    assert keypair_path.exists(), "keypair file must be written to disk"
    raw = json.loads(keypair_path.read_text())
    assert isinstance(raw, list), "stored keypair must be a JSON array"
    assert len(raw) == 64, "Solana keypair must be exactly 64 bytes"
    assert wallet.pubkey is not None


def test_new_keypair_file_permissions(tmp_path: Path) -> None:
    """Newly created keypair file must be owner read/write only (mode 0o600)."""
    keypair_path = tmp_path / "hardware.json"
    HardwareWallet.load_or_create(keypair_path)
    mode = keypair_path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_load_or_create_existing_keypair_round_trip(tmp_path: Path) -> None:
    """Loading from an existing file reproduces the identical public key."""
    keypair_path = tmp_path / "hardware.json"

    wallet1 = HardwareWallet.load_or_create(keypair_path)
    wallet2 = HardwareWallet.load_or_create(keypair_path)

    assert str(wallet1.pubkey) == str(wallet2.pubkey), "pubkey must be stable across loads"


def test_load_or_create_creates_parent_directories(tmp_path: Path) -> None:
    """Parent directories are created automatically if they do not exist."""
    keypair_path = tmp_path / "config" / "auxin" / "hardware.json"

    HardwareWallet.load_or_create(keypair_path)

    assert keypair_path.exists()


def test_different_wallets_have_different_pubkeys(tmp_path: Path) -> None:
    """Two independently created wallets must not share a public key."""
    w1 = HardwareWallet.load_or_create(tmp_path / "w1.json")
    w2 = HardwareWallet.load_or_create(tmp_path / "w2.json")
    assert str(w1.pubkey) != str(w2.pubkey)


# ── Identity ──────────────────────────────────────────────────────────────────


def test_pubkey_is_base58_string(tmp_path: Path) -> None:
    """Public key string representation is ASCII (base58) and non-empty."""
    wallet = HardwareWallet.load_or_create(tmp_path / "hardware.json")
    pubkey_str = str(wallet.pubkey)
    assert len(pubkey_str) > 0
    assert pubkey_str.isascii()


def test_solders_keypair_property_returns_keypair_instance(tmp_path: Path) -> None:
    """solders_keypair property exposes the raw Keypair for program clients."""
    wallet = HardwareWallet.load_or_create(tmp_path / "hardware.json")
    assert isinstance(wallet.solders_keypair, Keypair)


def test_solders_keypair_pubkey_matches_wallet_pubkey(tmp_path: Path) -> None:
    """The raw keypair's pubkey must match the wallet's pubkey property."""
    wallet = HardwareWallet.load_or_create(tmp_path / "hardware.json")
    assert str(wallet.solders_keypair.pubkey()) == str(wallet.pubkey)


# ── Transaction signing ───────────────────────────────────────────────────────


def test_sign_transaction_calls_sign_on_compatible_tx(tmp_path: Path) -> None:
    """sign_transaction delegates to tx.sign([keypair]) when the method exists."""
    wallet = HardwareWallet.load_or_create(tmp_path / "hardware.json")

    class MockTx:
        signed = False
        signers: list = []

        def sign(self, signers: list) -> None:
            self.signed = True
            self.signers = signers

    tx = MockTx()
    returned = wallet.sign_transaction(tx)

    assert tx.signed, "tx.sign() must be called"
    assert returned is tx, "the same transaction object must be returned"
    assert wallet.solders_keypair in tx.signers


def test_sign_transaction_returns_object_without_sign_method(tmp_path: Path) -> None:
    """sign_transaction returns the object unchanged when it has no sign() method."""
    wallet = HardwareWallet.load_or_create(tmp_path / "hardware.json")
    sentinel = object()
    result = wallet.sign_transaction(sentinel)
    assert result is sentinel


# ── Network integration (Devnet — skipped by default) ─────────────────────────


@pytest.mark.network
async def test_get_balance_returns_non_negative_int(tmp_path: Path) -> None:
    wallet = HardwareWallet.load_or_create(tmp_path / "hardware.json")
    balance = await wallet.get_balance("https://api.devnet.solana.com")
    assert isinstance(balance, int)
    assert balance >= 0


@pytest.mark.network
async def test_request_airdrop_returns_signature_string(tmp_path: Path) -> None:
    wallet = HardwareWallet.load_or_create(tmp_path / "hardware.json")
    sig = await wallet.request_airdrop("https://api.devnet.solana.com", 0.1)
    assert isinstance(sig, str)
    assert len(sig) > 0

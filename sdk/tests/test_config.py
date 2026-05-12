"""Tests for auxin_sdk.config — dual-cluster configuration layer."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from auxin_sdk.config import (
    DEVNET_PROGRAM_ID,
    ClusterConfig,
    _load_env_file,
    explorer_url,
    get_cluster_config,
)

# ── _load_env_file ────────────────────────────────────────────────────────────


def test_load_env_file_missing(tmp_path: Path) -> None:
    result = _load_env_file(tmp_path / "nonexistent.env")
    assert result == {}


def test_load_env_file_parses_key_value(tmp_path: Path) -> None:
    env = tmp_path / ".env.test"
    env.write_text("FOO=bar\nBAZ=qux\n")
    result = _load_env_file(env)
    assert result["FOO"] == "bar"
    assert result["BAZ"] == "qux"


def test_load_env_file_ignores_comments(tmp_path: Path) -> None:
    env = tmp_path / ".env.test"
    env.write_text("# comment\nKEY=value\n")
    result = _load_env_file(env)
    assert "# comment" not in result
    assert result["KEY"] == "value"


def test_load_env_file_strips_quotes(tmp_path: Path) -> None:
    env = tmp_path / ".env.test"
    env.write_text("QUOTED=\"hello world\"\nSINGLE='bye'\n")
    result = _load_env_file(env)
    assert result["QUOTED"] == "hello world"
    assert result["SINGLE"] == "bye"


# ── get_cluster_config — devnet (default) ─────────────────────────────────────


def test_get_cluster_config_defaults_to_devnet() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AUXIN_CLUSTER", None)
        cfg = get_cluster_config()
    assert cfg.cluster == "devnet"


def test_get_cluster_config_devnet_program_id() -> None:
    with patch.dict(os.environ, {"AUXIN_CLUSTER": "devnet"}, clear=False):
        os.environ.pop("PROGRAM_ID", None)
        cfg = get_cluster_config()
    assert cfg.program_id == DEVNET_PROGRAM_ID


def test_get_cluster_config_devnet_explorer_base() -> None:
    with patch.dict(os.environ, {"AUXIN_CLUSTER": "devnet"}, clear=False):
        cfg = get_cluster_config()
    assert cfg.explorer_base_url == "https://explorer.solana.com"


def test_get_cluster_config_devnet_returns_cluster_config_type() -> None:
    with patch.dict(os.environ, {"AUXIN_CLUSTER": "devnet"}, clear=False):
        cfg = get_cluster_config()
    assert isinstance(cfg, ClusterConfig)
    assert cfg.cluster == "devnet"


# ── get_cluster_config — mainnet ──────────────────────────────────────────────


def test_get_cluster_config_mainnet_cluster_field() -> None:
    with patch.dict(os.environ, {"AUXIN_CLUSTER": "mainnet"}, clear=False):
        cfg = get_cluster_config()
    assert cfg.cluster == "mainnet"


def test_get_cluster_config_mainnet_default_hw_path() -> None:
    with patch.dict(
        os.environ,
        {"AUXIN_CLUSTER": "mainnet"},
        clear=False,
    ):
        os.environ.pop("HARDWARE_KEYPAIR_PATH", None)
        os.environ.pop("HW_KEYPAIR_PATH", None)
        cfg = get_cluster_config()
    assert "mainnet" in cfg.hardware_keypair_path


def test_get_cluster_config_env_override_wins(tmp_path: Path) -> None:
    """PROGRAM_ID in os.environ overrides anything in the .env file."""
    override_id = "AaaBbbCccDddEeeFffGggHhhIiiJjjKkk111222333444"
    with patch.dict(
        os.environ,
        {"AUXIN_CLUSTER": "devnet", "PROGRAM_ID": override_id},
        clear=False,
    ):
        cfg = get_cluster_config()
    assert cfg.program_id == override_id


# ── explorer_url ──────────────────────────────────────────────────────────────


def test_explorer_url_devnet_includes_cluster_param() -> None:
    devnet_cfg = ClusterConfig(
        cluster="devnet",
        rpc_url="https://api.devnet.solana.com",
        program_id=DEVNET_PROGRAM_ID,
        hardware_keypair_path="~/.config/auxin/hardware_devnet.json",
        provider_pubkey="",
        explorer_base_url="https://explorer.solana.com",
    )
    url = explorer_url("5xSigABCDEF", devnet_cfg)
    assert "?cluster=devnet" in url
    assert "5xSigABCDEF" in url


def test_explorer_url_mainnet_no_cluster_param() -> None:
    mainnet_cfg = ClusterConfig(
        cluster="mainnet",
        rpc_url="https://mainnet.helius-rpc.com",
        program_id="SomeMainnetProgramId111111111111111111111111",
        hardware_keypair_path="~/.config/auxin/hardware_mainnet.json",
        provider_pubkey="",
        explorer_base_url="https://explorer.solana.com",
    )
    url = explorer_url("5xSigABCDEF", mainnet_cfg)
    assert "?cluster=devnet" not in url
    assert "5xSigABCDEF" in url
    assert "explorer.solana.com/tx/" in url


def test_explorer_url_uses_active_config_when_none_passed() -> None:
    with patch.dict(os.environ, {"AUXIN_CLUSTER": "devnet"}, clear=False):
        url = explorer_url("TestSig123")
    assert "TestSig123" in url

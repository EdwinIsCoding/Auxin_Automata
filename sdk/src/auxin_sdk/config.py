"""auxin_sdk/config.py
Dual-cluster configuration layer.

Reads AUXIN_CLUSTER (devnet | mainnet, default: devnet) and returns a
ClusterConfig populated from the matching .env file.

Usage
-----
    from auxin_sdk.config import get_cluster_config, explorer_url

    cfg = get_cluster_config()
    print(cfg.cluster, cfg.program_id)
    print(explorer_url("5xSig...", cfg))
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Canonical Devnet program ID — deployed April 2026.
DEVNET_PROGRAM_ID = "7sUSbF9zDN9QKVwA2ZGskg9gFgvbMuQpCdpt3hfgf1Mm"

# SDK root = three levels above this file (sdk/src/auxin_sdk/config.py → sdk/)
_SDK_ROOT = Path(__file__).parent.parent.parent


@dataclass(frozen=True)
class ClusterConfig:
    cluster: str  # "devnet" | "mainnet"
    rpc_url: str  # HTTP RPC endpoint
    program_id: str  # deployed program public key (base-58)
    hardware_keypair_path: str  # path to hardware wallet JSON
    provider_pubkey: str  # whitelisted provider public key (base-58, may be empty)
    explorer_base_url: str  # https://explorer.solana.com


def _load_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file and return key→value pairs (no shell expansion)."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip inline comments and surrounding quotes
        value = value.split("#")[0].strip().strip('"').strip("'")
        result[key.strip()] = value
    return result


def get_cluster_config() -> ClusterConfig:
    """
    Return a ClusterConfig for the active cluster.

    Resolution order for each field:
      1. Existing os.environ value (highest precedence — allows overrides)
      2. Value from the cluster-specific .env file
      3. Hard-coded default

    Cluster selection:
      AUXIN_CLUSTER=devnet  → loads sdk/.env.devnet  (falls back to sdk/.env)
      AUXIN_CLUSTER=mainnet → loads sdk/.env.mainnet
    """
    cluster = os.environ.get("AUXIN_CLUSTER", "devnet").lower().strip()

    if cluster == "mainnet":
        env_path = _SDK_ROOT / ".env.mainnet"
    else:
        cluster = "devnet"
        env_path = _SDK_ROOT / ".env.devnet"
        if not env_path.exists():
            env_path = _SDK_ROOT / ".env"  # pragma: no cover – legacy fallback

    file_vars = _load_env_file(env_path)

    def _get(key: str, default: str = "") -> str:
        """os.environ takes precedence over file; file takes precedence over default."""
        return os.environ.get(key) or file_vars.get(key, default)

    if cluster == "devnet":
        rpc_url = _get("HELIUS_RPC_URL") or _get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
        program_id = _get("PROGRAM_ID", DEVNET_PROGRAM_ID)
        hw_path = _get("HARDWARE_KEYPAIR_PATH") or _get(
            "HW_KEYPAIR_PATH", "~/.config/auxin/hardware_devnet.json"
        )
        provider_pubkey = _get("PROVIDER_PUBKEY", "")
    else:
        rpc_url = _get("HELIUS_RPC_URL") or _get("SOLANA_RPC_URL", "")
        program_id = _get("PROGRAM_ID", "")
        hw_path = _get("HARDWARE_KEYPAIR_PATH") or _get(
            "HW_KEYPAIR_PATH", "~/.config/auxin/hardware_mainnet.json"
        )
        provider_pubkey = _get("PROVIDER_PUBKEY", "")

    return ClusterConfig(
        cluster=cluster,
        rpc_url=rpc_url,
        program_id=program_id,
        hardware_keypair_path=hw_path,
        provider_pubkey=provider_pubkey,
        explorer_base_url="https://explorer.solana.com",
    )


def explorer_url(tx_signature: str, config: ClusterConfig | None = None) -> str:
    """
    Return a Solana Explorer link for the given transaction signature.

    Appends ?cluster=devnet for devnet; no suffix needed for mainnet
    (Explorer defaults to mainnet).
    """
    if config is None:
        config = get_cluster_config()
    base = f"{config.explorer_base_url}/tx/{tx_signature}"
    if config.cluster == "devnet":
        return f"{base}?cluster=devnet"
    return base

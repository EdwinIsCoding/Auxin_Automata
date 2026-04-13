"""auxin-sdk — Agentic infrastructure SDK for autonomous hardware on Solana."""

from .hashing import canonical_json, sha256_hex
from .logging import bind_request_id, configure_structlog, get_logger
from .schema import TelemetryFrame
from .sources.base import TelemetrySource
from .wallet import HardwareWallet

__all__ = [
    "HardwareWallet",
    "TelemetryFrame",
    "TelemetrySource",
    "canonical_json",
    "sha256_hex",
    "configure_structlog",
    "bind_request_id",
    "get_logger",
]

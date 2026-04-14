"""auxin-sdk — Agentic infrastructure SDK for autonomous hardware on Solana."""

from .hashing import canonical_json, sha256_hex
from .logging import bind_request_id, configure_structlog, get_logger
from .oracle import OracleDecision, SafetyOracle
from .schema import TelemetryFrame
from .sources.base import TelemetrySource
from .sources.mock import MockSource, ReplaySource
from .wallet import HardwareWallet

__all__ = [
    "HardwareWallet",
    "TelemetryFrame",
    "TelemetrySource",
    "MockSource",
    "ReplaySource",
    "SafetyOracle",
    "OracleDecision",
    "canonical_json",
    "sha256_hex",
    "configure_structlog",
    "bind_request_id",
    "get_logger",
]

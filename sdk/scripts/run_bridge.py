#!/usr/bin/env python3
"""Bridge entrypoint — reads AUXIN_SOURCE, wires everything, runs until SIGINT/SIGTERM.

Environment variables
─────────────────────
AUXIN_SOURCE          mock | twin | ros2  (default: mock)
HELIUS_RPC_URL        Helius or QuickNode RPC endpoint (preferred)
SOLANA_RPC_URL        Fallback RPC if HELIUS_RPC_URL not set
AUXIN_PROGRAM_ID      Optional — resolved from /programs/deployed.json if absent
HW_KEYPAIR_PATH       Path to hardware wallet JSON  (default: ~/.config/auxin/hardware.json)
OWNER_KEYPAIR_PATH    Path to owner wallet JSON     (default: ~/.config/auxin/owner.json)
PROVIDER_PUBKEY       Base58 provider public key — payments skipped if not set
GEMINI_API_KEY        Gemini API key — oracle falls back to local heuristic if absent
HELIUS_API_KEY        Helius API key for priority fee estimation (optional)
BRIDGE_WS_PORT        WebSocket broadcaster port   (default: 8766)
BRIDGE_HEALTHZ_PORT   Health endpoint port         (default: 8767)
AUXIN_MOCK_RATE_HZ    Frames/sec for MockSource    (default: 10)
AUXIN_MOCK_ANOMALY_EVERY  Anomaly injection period (default: 12)
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

# When invoked as `python scripts/run_bridge.py` from /sdk root,
# ensure the src/ package is importable without `pip install -e .`.
_SDK_ROOT = Path(__file__).parent.parent
if str(_SDK_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT / "src"))

import structlog  # noqa: E402

# ── Sentry (optional — only active when SENTRY_DSN is set) ───────────────────
_sentry_dsn = os.environ.get("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk as _sentry

    _sentry.init(dsn=_sentry_dsn, traces_sample_rate=0.2)

from auxin_sdk.bridge import Bridge, WebsocketBroadcaster  # noqa: E402
from auxin_sdk.logging import configure_structlog  # noqa: E402
from auxin_sdk.oracle import SafetyOracle  # noqa: E402
from auxin_sdk.program.client import AuxinProgramClient  # noqa: E402
from auxin_sdk.sources.base import TelemetrySource  # noqa: E402
from auxin_sdk.wallet import HardwareWallet  # noqa: E402

log = structlog.get_logger(__name__)


# ── Source factory — the ONLY place AUXIN_SOURCE is read ─────────────────────


def _build_source(source_name: str) -> TelemetrySource:
    """
    Instantiate the telemetry source selected by AUXIN_SOURCE.

    This function is the single location in the entire codebase that branches
    on source type.  Downstream code (Bridge, oracle, program client) never
    checks which source is active — they only call source.stream().
    """
    name = source_name.lower().strip()

    if name == "mock":
        from auxin_sdk.sources.mock import MockSource

        rate_hz = float(os.environ.get("AUXIN_MOCK_RATE_HZ", "10"))
        anomaly_every = int(os.environ.get("AUXIN_MOCK_ANOMALY_EVERY", "12"))
        log.info("source.selected", kind="mock", rate_hz=rate_hz, anomaly_every=anomaly_every)
        return MockSource(rate_hz=rate_hz, anomaly_every=anomaly_every)

    if name == "twin":
        # TwinSource lives in /twin workspace; installed as `twin` package or on PYTHONPATH
        from twin.source import TwinSource  # type: ignore[import-untyped]

        log.info("source.selected", kind="twin")
        return TwinSource()

    if name == "ros2":
        # ROS2Source lives in /edge workspace
        from auxin_edge.ros2_source import ROS2Source  # type: ignore[import-untyped]

        log.info("source.selected", kind="ros2")
        return ROS2Source()

    raise ValueError(f"Unknown AUXIN_SOURCE={source_name!r}. Valid values: mock, twin, ros2")


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    configure_structlog()

    # ── Config from env ───────────────────────────────────────────────────────
    source_name = os.environ.get("AUXIN_SOURCE", "mock")

    rpc_url = (
        os.environ.get("HELIUS_RPC_URL")
        or os.environ.get("SOLANA_RPC_URL")
        or "https://api.devnet.solana.com"
    )

    program_id = os.environ.get("AUXIN_PROGRAM_ID")  # None → resolved from deployed.json

    hw_path = os.environ.get("HW_KEYPAIR_PATH", "~/.config/auxin/hardware.json")
    owner_path = os.environ.get("OWNER_KEYPAIR_PATH", "~/.config/auxin/owner.json")

    ws_port = int(os.environ.get("BRIDGE_WS_PORT", "8766"))
    healthz_port = int(os.environ.get("BRIDGE_HEALTHZ_PORT", "8767"))

    # ── Wallets ───────────────────────────────────────────────────────────────
    hw_wallet = HardwareWallet.load_or_create(hw_path)
    owner_wallet = HardwareWallet.load_or_create(owner_path)
    log.info(
        "bridge.wallets_ready",
        hw=str(hw_wallet.pubkey),
        owner=str(owner_wallet.pubkey),
    )

    # ── Provider (optional) ───────────────────────────────────────────────────
    from solders.pubkey import Pubkey

    provider_str = os.environ.get("PROVIDER_PUBKEY")
    provider_pubkey = Pubkey.from_string(provider_str) if provider_str else None

    # ── Oracle ────────────────────────────────────────────────────────────────
    oracle = SafetyOracle(api_key=os.environ.get("GEMINI_API_KEY"))

    # ── Source ────────────────────────────────────────────────────────────────
    source = _build_source(source_name)

    # ── WebSocket broadcaster ─────────────────────────────────────────────────
    ws_broadcaster = WebsocketBroadcaster(port=ws_port)

    helius_api_key = os.environ.get("HELIUS_API_KEY")

    log.info(
        "bridge.config",
        source=source_name,
        rpc_url=rpc_url,
        ws_port=ws_port,
        healthz_port=healthz_port,
        provider=str(provider_pubkey) if provider_pubkey else "not_set",
        gemini=bool(os.environ.get("GEMINI_API_KEY")),
    )

    # ── Program client (async context manager owns the RPC connection) ────────
    async with AuxinProgramClient.connect(
        rpc_url=rpc_url,
        program_id=program_id,
    ) as program_client:
        bridge = Bridge(
            source=source,
            oracle=oracle,
            program_client=program_client,
            wallet=hw_wallet,
            ws_broadcaster=ws_broadcaster,
            owner_pubkey=owner_wallet.pubkey,
            provider_pubkey=provider_pubkey,
            rpc_url=rpc_url,
            helius_api_key=helius_api_key,
            healthz_port=healthz_port,
        )

        # ── Graceful SIGINT / SIGTERM shutdown ────────────────────────────────
        loop = asyncio.get_running_loop()
        bridge_task = asyncio.create_task(bridge.run(), name="bridge-main")

        def _on_signal(sig: signal.Signals) -> None:
            log.info("bridge.signal_received", signal=sig.name)
            bridge_task.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_signal, sig)

        try:
            await bridge_task
        except asyncio.CancelledError:
            log.info("bridge.clean_exit")

    log.info("bridge.exited")


if __name__ == "__main__":
    asyncio.run(main())

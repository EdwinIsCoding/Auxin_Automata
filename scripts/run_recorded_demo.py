#!/usr/bin/env python3
"""run_recorded_demo.py — Single-command launcher for the Auxin Recorded Replay demo.

Validates the episode directory and wallet balance, then starts the bridge in
recorded mode with live Gemini oracle calls and Solana mainnet payments.

Usage
-----
python scripts/run_recorded_demo.py \\
  --episode-dir /path/to/episode_dir \\
  --playback-speed 0.8 \\
  --camera-key ee_zed_m_left \\
  --cluster mainnet

For grant milestone recording:
  python scripts/run_recorded_demo.py --episode-dir data/ --playback-speed 0.8

Then open http://localhost:3000 and start your screen recorder.
After the demo, press Ctrl+C to get the session summary, then run:
  python scripts/generate_demo_report.py --logs /tmp/auxin_demo_logs/
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── Resolve paths ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parent.parent
_SDK_DIR = _REPO_ROOT / "sdk"
_RUN_BRIDGE = _SDK_DIR / "scripts" / "run_bridge.py"


# ── Validation ────────────────────────────────────────────────────────────────


def validate_episode_dir(episode_dir: Path) -> None:
    """Raise SystemExit if the episode directory is missing required files."""
    errors: list[str] = []

    if not episode_dir.exists():
        print(f"[ERROR] Episode directory not found: {episode_dir}")
        sys.exit(1)

    required = ["robot.jsonl", "session_metadata.json"]
    for name in required:
        if not (episode_dir / name).exists():
            errors.append(f"  Missing: {episode_dir / name}")

    cameras_dir = episode_dir / "cameras"
    if not cameras_dir.exists():
        errors.append(f"  Missing cameras/ directory: {cameras_dir}")
    else:
        # At least one camera must have an rgb.mp4
        mp4_files = list(cameras_dir.glob("*/rgb.mp4"))
        if not mp4_files:
            errors.append(f"  No rgb.mp4 found under {cameras_dir}")

    if errors:
        print("[ERROR] Episode directory is missing required files:")
        for e in errors:
            print(e)
        sys.exit(1)


def get_episode_name(episode_dir: Path) -> str:
    """Read the recording ID from session_metadata.json, fall back to dirname."""
    meta_path = episode_dir / "session_metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return str(meta.get("recording_id", episode_dir.name))
        except Exception:
            pass
    return episode_dir.name


def get_robot_frame_count(episode_dir: Path) -> int:
    """Count lines in robot.jsonl."""
    path = episode_dir / "robot.jsonl"
    try:
        with path.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return 0


def get_wallet_balance_sol(rpc_url: str, pubkey_str: str) -> float | None:
    """Fetch SOL balance via RPC. Returns None on any error."""
    try:
        import urllib.request
        import urllib.error

        body = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [pubkey_str, {"commitment": "confirmed"}],
        }).encode()
        req = urllib.request.Request(
            rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            lamports = data.get("result", {}).get("value", 0)
            return lamports / 1_000_000_000
    except Exception:
        return None


def get_hw_pubkey(hw_keypair_path: str) -> str | None:
    """Extract public key from hardware wallet keypair JSON."""
    try:
        import base64

        path = Path(hw_keypair_path).expanduser()
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        # solana-keygen format: list of 64 ints (private + public bytes)
        if isinstance(raw, list) and len(raw) == 64:
            from solders.keypair import Keypair  # type: ignore[import-untyped]
            kp = Keypair.from_bytes(bytes(raw))
            return str(kp.pubkey())
    except Exception:
        pass
    return None


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch the Auxin Recorded Replay demo (Franka LeRobot data + live mainnet payments)"
    )
    parser.add_argument(
        "--episode-dir",
        required=True,
        type=Path,
        help="Path to a LeRobot episode directory containing robot.jsonl",
    )
    parser.add_argument(
        "--playback-speed",
        type=float,
        default=1.0,
        help="Replay speed multiplier (default: 1.0, use 0.8 for smoother demo recording)",
    )
    parser.add_argument(
        "--camera-key",
        default="ee_zed_m_left",
        help="Camera to use for Gemini oracle frames (default: ee_zed_m_left)",
    )
    parser.add_argument(
        "--cluster",
        default="mainnet",
        choices=["devnet", "mainnet"],
        help="Solana cluster (default: mainnet)",
    )
    parser.add_argument(
        "--oracle-interval",
        type=int,
        default=30,
        help="Oracle check every N frames (default: 30 → ~1 call/sec at 30fps)",
    )
    parser.add_argument(
        "--payment-lamports",
        type=int,
        default=1000,
        help="Lamports per oracle call (default: 1000 = 0.000001 SOL)",
    )
    parser.add_argument(
        "--no-loop",
        action="store_true",
        help="Play the episode once then stop (default: loop indefinitely)",
    )
    args = parser.parse_args()

    episode_dir = args.episode_dir.resolve()

    # ── Pre-flight validation ─────────────────────────────────────────────────

    validate_episode_dir(episode_dir)

    episode_name = get_episode_name(episode_dir)
    frame_count = get_robot_frame_count(episode_dir)

    # Wallet info
    hw_keypair_path = os.environ.get(
        "HW_KEYPAIR_PATH", str(Path.home() / ".config/auxin/hardware.json")
    )
    rpc_url = (
        os.environ.get("HELIUS_RPC_URL")
        or os.environ.get("SOLANA_RPC_URL")
        or (
            "https://api.mainnet-beta.solana.com"
            if args.cluster == "mainnet"
            else "https://api.devnet.solana.com"
        )
    )

    hw_pubkey = get_hw_pubkey(hw_keypair_path)
    balance = None
    if hw_pubkey:
        balance = get_wallet_balance_sol(rpc_url, hw_pubkey)

    if args.cluster == "mainnet" and balance is not None and balance < 0.1:
        print(
            f"\n[WARN] Hardware wallet balance is {balance:.4f} SOL — "
            "consider topping up before a long demo (recommended >= 0.1 SOL)\n"
        )

    # ── Startup summary ───────────────────────────────────────────────────────

    print()
    print("=" * 45)
    print("   Auxin Automata — Recorded Data Replay")
    print("=" * 45)
    print(f"  Episode    : {episode_name}")
    print(f"  Directory  : {episode_dir}")
    print(f"  Frames     : {frame_count:,} robot frames")
    print(f"  Camera     : {args.camera_key}")
    print(f"  Cluster    : {args.cluster.upper()}")
    if hw_pubkey:
        balance_str = f"{balance:.4f} SOL" if balance is not None else "unknown"
        print(f"  HW Wallet  : {hw_pubkey[:20]}… ({balance_str})")
    print(f"  Speed      : {args.playback_speed}x")
    print(f"  Loop       : {'no' if args.no_loop else 'yes'}")
    print(f"  Oracle     : every {args.oracle_interval} frames")
    print(f"  Payment    : {args.payment_lamports} lamports/call")
    print(f"  Dashboard  : http://localhost:3000")
    print("=" * 45)
    print()
    print("  Press Ctrl+C to stop and see session summary.")
    print()

    # ── Build environment for bridge ──────────────────────────────────────────

    env = os.environ.copy()
    env.update({
        "AUXIN_SOURCE": "recorded",
        "AUXIN_CLUSTER": args.cluster,
        "AUXIN_EPISODE_DIR": str(episode_dir),
        "AUXIN_PLAYBACK_SPEED": str(args.playback_speed),
        "AUXIN_CAMERA_KEY": args.camera_key,
        "AUXIN_LOOP": "0" if args.no_loop else "1",
        "AUXIN_ORACLE_INTERVAL_FRAMES": str(args.oracle_interval),
        "AUXIN_PAYMENT_LAMPORTS": str(args.payment_lamports),
        # Structured log output to file for generate_demo_report.py
        "STRUCTLOG_OUTPUT_FILE": "/tmp/auxin_demo_logs/bridge.jsonl",
    })

    # ── Start bridge ──────────────────────────────────────────────────────────

    Path("/tmp/auxin_demo_logs").mkdir(parents=True, exist_ok=True)

    start_time = time.monotonic()

    bridge_cmd = [
        sys.executable,
        str(_RUN_BRIDGE),
    ]

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            bridge_cmd,
            cwd=str(_SDK_DIR),
            env=env,
        )
        proc.wait()
    except KeyboardInterrupt:
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        elapsed = time.monotonic() - start_time

        # ── Session summary ───────────────────────────────────────────────────
        print()
        print("=" * 45)
        print("   Session Summary")
        print("=" * 45)
        print(f"  Duration   : {elapsed:.1f}s ({elapsed/60:.1f} min)")
        print(f"  Episode    : {episode_name}")
        print(f"  Cluster    : {args.cluster.upper()}")
        print()
        print("  To generate a grant milestone report:")
        print("  python scripts/generate_demo_report.py \\")
        print("    --logs /tmp/auxin_demo_logs/ \\")
        print(f"    --episode {episode_name}")
        print("=" * 45)


if __name__ == "__main__":
    main()

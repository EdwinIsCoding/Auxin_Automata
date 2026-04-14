"""CLI entrypoint: ``python -m twin --mode [video|ws|both]``

Examples
--------
Stream JPEG frames over WebSocket (default):

    python -m twin

Render a 10-second MP4 to ./twin_demo.mp4:

    python -m twin --mode video --n-frames 300 --output twin_demo.mp4

Both — render first, then start the WebSocket server:

    python -m twin --mode both --output twin_demo.mp4

Environment variable overrides (from .env.example):

    TWIN_MODE=ws TWIN_WS_PORT=8765 python -m twin
"""

from __future__ import annotations

import argparse
import asyncio
import os


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twin",
        description="Auxin Twin — PyBullet digital twin for Auxin Automata",
    )
    parser.add_argument(
        "--mode",
        choices=["video", "ws", "both"],
        default=os.getenv("TWIN_MODE", "ws"),
        help="Operation mode: 'video' renders an MP4, 'ws' starts the WebSocket server, "
        "'both' renders then serves. (env: TWIN_MODE)",
    )
    parser.add_argument(
        "--rate-hz",
        type=float,
        default=float(os.getenv("TWIN_TELEMETRY_RATE_HZ", "10")),
        help="TwinSource telemetry rate in Hz. (env: TWIN_TELEMETRY_RATE_HZ)",
    )
    parser.add_argument(
        "--output",
        default=os.getenv("TWIN_VIDEO_OUTPUT", "twin_demo.mp4"),
        help="MP4 output path (used when mode=video or mode=both). (env: TWIN_VIDEO_OUTPUT)",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="WebSocket bind host. Default: localhost",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("TWIN_WS_PORT", "8765")),
        help="WebSocket bind port. (env: TWIN_WS_PORT)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=int(os.getenv("TWIN_VIDEO_FPS", "30")),
        help="FPS for MP4 output / WebSocket broadcast. (env: TWIN_VIDEO_FPS)",
    )
    parser.add_argument(
        "--n-frames",
        type=int,
        default=300,
        help="Number of frames to render in video mode. Default: 300 (10s at 30fps)",
    )
    parser.add_argument(
        "--sim-rate-hz",
        type=float,
        default=float(os.getenv("PYBULLET_SIM_RATE_HZ", "240")),
        help="PyBullet simulation rate in Hz. (env: PYBULLET_SIM_RATE_HZ)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch PyBullet with GUI window (requires a display).",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    from .scene import RobotScene
    from .trajectory import PickAndPlace

    # sim_steps_per_frame: how many physics steps between rendered frames
    sim_steps_per_frame = max(1, round(args.sim_rate_hz / args.fps))

    scene = RobotScene(gui=args.gui, sim_rate_hz=args.sim_rate_hz)
    trajectory = PickAndPlace()

    try:
        if args.mode == "video":
            _run_video(scene, trajectory, args, sim_steps_per_frame)
        elif args.mode == "ws":
            _run_ws(scene, trajectory, args, sim_steps_per_frame)
        elif args.mode == "both":
            _run_video(scene, trajectory, args, sim_steps_per_frame)
            trajectory.reset()
            _run_ws(scene, trajectory, args, sim_steps_per_frame)
    finally:
        scene.close()


def _run_video(
    scene: "RobotScene",
    trajectory: "PickAndPlace",
    args: argparse.Namespace,
    sim_steps_per_frame: int,
) -> None:
    from .render import render_video

    output = render_video(
        scene,
        trajectory,
        output_path=args.output,
        fps=args.fps,
        n_frames=args.n_frames,
        sim_steps_per_frame=sim_steps_per_frame,
    )
    print(f"Video saved to {output}")


def _run_ws(
    scene: "RobotScene",
    trajectory: "PickAndPlace",
    args: argparse.Namespace,
    sim_steps_per_frame: int,
) -> None:
    from .render import serve_ws

    print(f"Starting WebSocket server on ws://{args.host}:{args.port}")
    print("Press Ctrl-C to stop.")
    try:
        asyncio.run(
            serve_ws(
                scene,
                trajectory,
                host=args.host,
                port=args.port,
                target_fps=args.fps,
                sim_steps_per_frame=sim_steps_per_frame,
            )
        )
    except KeyboardInterrupt:
        print("\nWebSocket server stopped.")


if __name__ == "__main__":
    main()

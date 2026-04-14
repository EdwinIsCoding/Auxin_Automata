"""Off-screen MP4 renderer and WebSocket JPEG-frame server.

Two entry points
----------------
render_video(scene, trajectory, output_path, ...)
    Render *n_frames* of simulation to an MP4 file using imageio-ffmpeg.
    Returns the Path to the written file.

serve_ws(scene, trajectory, host, port, ...)
    Broadcast base64-encoded JPEG frames over WebSocket at ws://host:port.
    Each message is a JSON object: {"type": "frame", "data": "<base64>"}
    Runs until interrupted (Ctrl-C or task cancellation).

Both functions run the PyBullet simulation forward at *sim_steps_per_frame*
steps per rendered/broadcast frame.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

import imageio
import numpy as np
import structlog
from PIL import Image

if TYPE_CHECKING:
    from .scene import RobotScene
    from .trajectory import PickAndPlace

log = structlog.get_logger(__name__)

# Default render resolution
_WIDTH: int = 320
_HEIGHT: int = 240


# ── Video rendering ───────────────────────────────────────────────────────────


def render_video(
    scene: "RobotScene",
    trajectory: "PickAndPlace",
    output_path: str | Path,
    fps: int = 30,
    n_frames: int = 300,
    width: int = 640,
    height: int = 480,
    sim_steps_per_frame: int = 8,
) -> Path:
    """
    Render *n_frames* of simulation to an MP4 file.

    Parameters
    ----------
    scene
        Live RobotScene to render.
    trajectory
        PickAndPlace planner driving the robot arm.
    output_path
        Destination MP4 file path.  Parent directories are created if absent.
    fps
        Frames per second in the output video.
    n_frames
        Total number of frames to render.
    width, height
        Render resolution in pixels.
    sim_steps_per_frame
        How many PyBullet simulation steps to advance per rendered frame.

    Returns
    -------
    Path
        Absolute path to the written MP4 file.
    """
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    log.info("render.video_start", output=str(output), n_frames=n_frames, fps=fps)

    writer = imageio.get_writer(str(output), fps=fps)
    try:
        for i in range(n_frames):
            for _ in range(sim_steps_per_frame):
                trajectory.step(scene)
            jpeg_bytes = scene.capture_frame(width, height)
            rgb = _jpeg_to_numpy(jpeg_bytes, width, height)
            writer.append_data(rgb)

            if i % 30 == 0:
                log.debug("render.video_progress", frame=i, total=n_frames)
    finally:
        writer.close()

    log.info("render.video_done", output=str(output))
    return output


# ── WebSocket server ──────────────────────────────────────────────────────────


async def serve_ws(
    scene: "RobotScene",
    trajectory: "PickAndPlace",
    host: str = "localhost",
    port: int = 8765,
    target_fps: int = 30,
    sim_steps_per_frame: int = 8,
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> None:
    """
    Stream base64-encoded JPEG frames to all connected WebSocket clients.

    Each message is a compact JSON object::

        {"type": "frame", "data": "<base64-encoded JPEG>"}

    The server runs indefinitely until the task is cancelled.
    Multiple simultaneous clients are supported; all receive the same frames.

    Parameters
    ----------
    scene
        Live RobotScene to render.
    trajectory
        PickAndPlace planner driving the robot arm.
    host / port
        Bind address.  Default: localhost:8765.
    target_fps
        Target broadcast rate.  Actual rate may be lower under load.
    sim_steps_per_frame
        Sim steps advanced between rendered frames.
    width, height
        JPEG frame dimensions.
    """
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover
        raise ImportError("websockets is required for serve_ws()") from exc

    frame_dt = 1.0 / target_fps
    clients: set[websockets.WebSocketServerProtocol] = set()  # type: ignore[name-defined]

    async def _handler(ws: "websockets.WebSocketServerProtocol", path: str) -> None:  # noqa: ARG001
        clients.add(ws)
        log.info("ws.client_connected", remote=ws.remote_address, total=len(clients))
        try:
            await ws.wait_closed()
        finally:
            clients.discard(ws)
            log.info("ws.client_disconnected", remote=ws.remote_address, total=len(clients))

    async def _broadcast_loop() -> None:
        while True:
            # Advance sim
            for _ in range(sim_steps_per_frame):
                trajectory.step(scene)

            # Render
            jpeg_bytes = scene.capture_frame(width, height)
            payload = json.dumps(
                {"type": "frame", "data": base64.b64encode(jpeg_bytes).decode("ascii")}
            )

            # Fan-out to all connected clients
            if clients:
                await asyncio.gather(
                    *(ws.send(payload) for ws in set(clients)),
                    return_exceptions=True,
                )

            await asyncio.sleep(frame_dt)

    log.info("ws.server_starting", host=host, port=port)
    async with websockets.serve(_handler, host, port):
        await _broadcast_loop()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _jpeg_to_numpy(jpeg_bytes: bytes, width: int, height: int) -> np.ndarray:
    """Decode JPEG bytes to an (H, W, 3) uint8 numpy array."""
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    return np.array(img, dtype=np.uint8)

# auxin-twin

PyBullet digital twin for Auxin Automata — Phase 1C.

Provides `TwinSource`, a drop-in `TelemetrySource` implementation backed by a
Franka Panda simulation instead of physical hardware.

## Quick start

```bash
cd twin
uv sync
python -m twin --mode ws          # WebSocket server on ws://localhost:8765
python -m twin --mode video       # render twin_demo.mp4 (300 frames)
python -m twin --mode both        # render then serve
```

## Running tests

```bash
uv run pytest
```

## Architecture

| Module | Purpose |
|---|---|
| `scene.py` | PyBullet scene: Franka Panda URDF, table, obstacle box, JPEG capture |
| `trajectory.py` | Pre-scripted pick-and-place IK loop |
| `source.py` | `TwinSource(TelemetrySource)` — the agnosticism-contract implementation |
| `render.py` | Off-screen MP4 renderer + WebSocket JPEG-frame server |
| `__main__.py` | CLI entrypoint |

## Environment variables

See `.env.example` for all configurable knobs (`TWIN_MODE`, `TWIN_WS_PORT`,
`TWIN_VIDEO_OUTPUT`, `TWIN_VIDEO_FPS`, `PYBULLET_SIM_RATE_HZ`,
`TWIN_TELEMETRY_RATE_HZ`).

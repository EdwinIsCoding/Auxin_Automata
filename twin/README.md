# auxin-twin

PyBullet digital twin for Auxin Automata. The insurance policy: if the physical arm is unavailable, the twin carries the full demo end-to-end. `TwinSource` is byte-identical in interface to `ROS2Source` — switching between them is one env var.

→ [Root README](../README.md)

---

## Purpose

The twin serves two roles:

1. **Development** — validate the bridge, oracle, and dashboard without hardware. `AUXIN_SOURCE=twin` selects it; zero code changes downstream.
2. **Demo fallback** — if the physical arm (Track B, Jetson + myCobot) is unavailable, the twin produces a visually compelling demo that proves all three architectural pillars.

---

## Structure

```
twin/
├── src/twin/
│   ├── scene.py        PyBullet scene: Franka Panda URDF, table, obstacle box
│   ├── trajectory.py   Pre-scripted IK pick-and-place loop (repeating)
│   ├── source.py       TwinSource(TelemetrySource) — agnosticism contract impl
│   ├── render.py       Off-screen MP4 renderer + WS JPEG-frame server (:8765)
│   └── __main__.py     CLI entrypoint
└── tests/              Smoke tests: 100 frames stream + schema validation
```

---

## Install

```bash
cd twin
uv sync
```

PyBullet requires no GPU; headless rendering uses EGL or software rasterizer.

---

## Test

```bash
cd twin
uv run pytest
```

---

## Run

```bash
cd twin

# WebSocket mode — streams JPEG frames to dashboard TwinViewport
python -m twin --mode ws
# Frames available at ws://localhost:8765

# Render to MP4 (300 frames at 30 fps = 10s clip)
python -m twin --mode video

# Both (render first, then start WS server)
python -m twin --mode both
```

Environment knobs: `TWIN_WS_PORT` (default 8765), `TWIN_VIDEO_OUTPUT`, `TWIN_VIDEO_FPS`, `PYBULLET_SIM_RATE_HZ` (default 240), `TWIN_TELEMETRY_RATE_HZ` (default 10). See `.env.example`.

---

## TwinSource Interface

`TwinSource` implements the `TelemetrySource` ABC from `auxin-sdk`:

```python
from twin.source import TwinSource

source = TwinSource()
async for frame in source.stream():
    # frame is a TelemetryFrame — identical schema to MockSource and ROS2Source
    print(frame.joint_positions)
```

The bridge selects it via `AUXIN_SOURCE=twin`. This is the only line that changes when switching from mock to twin mode.

---

## How It Fits

```
PyBullet sim (240 Hz internal)
        ↓ getJointStates at 10 Hz
    TwinSource.stream()   →   Bridge (auxin-sdk)   →   Solana + Dashboard
        ↓ JPEG frames (base64)
    render.py WS :8765    →   Dashboard TwinViewport
```

The twin runs as a standalone process. The bridge imports `TwinSource` and uses it identically to `MockSource`. See the [root architecture diagram](../README.md#architecture).

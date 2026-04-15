# auxin-twin

PyBullet digital twin for Auxin Automata. The demo insurance policy: if the physical arm is unavailable, the twin carries the full end-to-end demo. `TwinSource` is byte-identical in interface to `ROS2Source` — switching between them is one env var change.

→ [Root README](../README.md)

---

## Purpose

The twin serves two roles:

1. **Development vehicle** — validate the bridge, oracle, and dashboard without hardware. `AUXIN_SOURCE=twin` selects it; zero code changes downstream.
2. **Demo fallback** — if the physical arm (Track B, Jetson + myCobot) is unavailable, the twin produces a visually compelling demo that proves all three architectural pillars end-to-end.

A Franka Panda URDF runs an IK pick-and-place loop at 240 Hz internally. Joint states are sampled at 10 Hz and emitted as `TelemetryFrame` objects, identical in schema to what the ROS2 nodes produce.

---

## Structure

```
twin/
├── src/twin/
│   ├── scene.py        PyBullet scene: Franka Panda URDF, table, obstacle box
│   ├── trajectory.py   Pre-scripted IK pick-and-place loop (indefinite repeat)
│   ├── source.py       TwinSource(TelemetrySource) — implements the agnosticism contract
│   ├── render.py       Off-screen MP4 renderer + WebSocket JPEG-frame server (:8765)
│   └── __main__.py     CLI entrypoint
└── tests/
    └── test_twin_source.py  Smoke tests: 100 frames stream, schema validation, IK checks
```

---

## Install

```bash
cd twin
uv sync
```

PyBullet runs headless — no GPU required. EGL or software rasterizer is used for off-screen rendering.

---

## Test

```bash
cd twin
uv run python -m pytest
```

16/16 tests pass. Covers: schema validation, 100-frame smoke, joint count, end-effector pose structure, interface interchangeability with `MockSource`.

---

## Run

```bash
cd twin

# WebSocket mode — streams JPEG frames to dashboard TwinViewport
python -m twin --mode ws
# ws://localhost:8765

# MP4 render (300 frames at 30 fps = 10 s clip)
python -m twin --mode video

# Both: render first, then start WS server
python -m twin --mode both
```

Environment knobs: `TWIN_WS_PORT` (default 8765), `TWIN_VIDEO_OUTPUT`, `TWIN_VIDEO_FPS` (default 30), `TWIN_TELEMETRY_RATE_HZ` (default 10), `PYBULLET_SIM_RATE_HZ` (default 240). See `.env.example`.

---

## TwinSource Interface

`TwinSource` implements the `TelemetrySource` ABC from `auxin-sdk`:

```python
from twin.source import TwinSource

source = TwinSource()
async for frame in source.stream():
    # frame: TelemetryFrame — same schema as MockSource and ROS2Source
    print(frame.joint_positions)   # 7 joints (Franka Panda)
    print(frame.end_effector_pose) # {"x": ..., "y": ..., "z": ..., "qx": ..., ...}
```

The bridge selects it via `AUXIN_SOURCE=twin`. That is the only line that changes when switching from mock to twin mode. No conditional branches anywhere in bridge or downstream code.

---

## How It Fits

```
PyBullet sim (240 Hz internal)
        ↓ getJointStates sampled at 10 Hz
    TwinSource.stream()    →  Bridge (auxin-sdk)  →  Solana + Dashboard
        ↓ JPEG frames base64
    render.py WS :8765     →  Dashboard TwinViewport
```

The twin runs as a standalone process. The bridge imports `TwinSource` and uses it identically to `MockSource`. See the [root architecture diagram](../README.md#architecture).

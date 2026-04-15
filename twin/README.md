# auxin-twin

PyBullet digital twin for Auxin Automata. The demo insurance policy: if the physical arm is unavailable, the twin carries the full end-to-end demo. `TwinSource` is byte-identical in interface to `ROS2Source` — switching between them is one env var change.

→ [Root README](../README.md)

---

## Purpose

The twin serves two roles:

1. **Development vehicle** — validate the bridge, oracle, and dashboard without hardware. `AUXIN_SOURCE=twin` selects it; zero code changes downstream.
2. **Demo fallback** — if the physical arm (Track B) is unavailable, the twin produces a visually compelling demo that proves all three architectural pillars end-to-end.

A Franka Panda URDF runs an IK pick-and-place loop at 240 Hz internally. Joint states are sampled at 10 Hz and emitted as `TelemetryFrame` objects, identical in schema to what the ROS2 nodes produce. PyBullet contact detection populates `anomaly_flags` when the arm collides with the obstacle — the same flag that triggers the compliance log path in the bridge.

---

## Structure

```
twin/
├── src/twin/
│   ├── scene.py        PyBullet scene: Franka Panda URDF, table, red obstacle box
│   │                   has_collision() · teleport_obstacle_to_eef()
│   ├── trajectory.py   Pre-scripted IK pick-and-place loop (indefinite repeat)
│   ├── source.py       TwinSource(TelemetrySource) — agnosticism contract
│   │                   TWIN_FORCE_COLLISION support for E2E testing
│   ├── render.py       Off-screen MP4 renderer + WebSocket JPEG-frame server (:8765)
│   └── __main__.py     CLI entrypoint (--mode video|ws|both)
└── tests/
    └── test_twin_source.py  16 tests: schema validation, 100-frame smoke, IK, collision
```

---

## Install

```bash
cd twin
uv sync
```

PyBullet runs headless — no GPU required. `ER_TINY_RENDERER` handles off-screen rendering without an OpenGL context or display.

---

## Test

```bash
cd twin
uv run python -m pytest
```

**16/16 tests pass.** Covers: schema validation, 100-frame smoke, joint count (7), EEF pose structure, source interface interchangeability with `MockSource`, collision detection.

---

## Run

```bash
cd twin

# WebSocket mode — streams JPEG frames to dashboard TwinViewport
python -m twin --mode ws          # ws://localhost:8765

# Force a collision after frame 30 (E2E anomaly demo)
TWIN_FORCE_COLLISION=30 python -m twin --mode ws

# MP4 render (300 frames @ 30 fps = 10 s clip)
python -m twin --mode video

# Both: render first, then start WS server
python -m twin --mode both
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TWIN_MODE` | `ws` | `video` \| `ws` \| `both` |
| `TWIN_WS_PORT` | `8765` | JPEG frame WebSocket port |
| `TWIN_FORCE_COLLISION` | `0` | Teleport obstacle onto EEF after N frames (0 = disabled) |
| `TWIN_VIDEO_OUTPUT` | `twin_demo.mp4` | MP4 output path |
| `TWIN_VIDEO_FPS` | `30` | MP4 frame rate |
| `TWIN_TELEMETRY_RATE_HZ` | `10` | Telemetry output rate to bridge |
| `PYBULLET_SIM_RATE_HZ` | `240` | Internal simulation rate |

---

## Collision Detection

`scene.py` exposes two methods added in Phase 3:

```python
scene.has_collision() -> bool
# Returns True when any robot link contacts the obstacle (PyBullet getContactPoints).

scene.teleport_obstacle_to_eef()
# Moves the obstacle to the current EEF position and steps physics once.
# Used by TWIN_FORCE_COLLISION for deterministic E2E testing.
```

`TwinSource._stream()` calls `scene.has_collision()` every frame and sets `anomaly_flags=["collision_detected"]` when True. This is the same flag the bridge reads to route frames to the compliance queue.

---

## TwinSource Interface

```python
from twin.source import TwinSource

source = TwinSource()
async for frame in source.stream():
    # frame: TelemetryFrame — same schema as MockSource and ROS2Source
    print(frame.joint_positions)    # list[float], 7 joints
    print(frame.end_effector_pose)  # {"x":…, "y":…, "z":…, "qx":…, "qy":…, "qz":…, "qw":…}
    print(frame.anomaly_flags)      # [] or ["collision_detected"]
```

---

## How It Fits

```
PyBullet (240 Hz internal) → sample at 10 Hz → TwinSource.stream()
    ↓ TelemetryFrame (anomaly_flags populated on collision)
Bridge (auxin-sdk) → oracle → Solana + Dashboard WS

PyBullet render → JPEG base64 frames → WS :8765 → Dashboard TwinViewport
```

See the [root architecture diagram](../README.md#architecture).

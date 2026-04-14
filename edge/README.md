# edge

ROS2 Python nodes for the NVIDIA Jetson Orin Nano. Bridges a physical robotic arm into the Auxin Automata SDK, and independently monitors hardware safety without any network dependency.

→ [Root README](../README.md)

---

## Purpose

Two nodes, two jobs, deliberately separate processes:

**`telemetry_bridge_node`** — subscribes to `/joint_states`, throttles to 2 Hz, converts to `TelemetryFrame`, and feeds the `ROS2Source` queue consumed by the Python bridge. It uses `auxin-sdk` and is network-aware.

**`safety_watchdog_node`** — subscribes to `/joint_states` at full rate, monitors torque, and calls `/emergency_stop` if thresholds are exceeded for 3 consecutive frames. It is **completely independent**: no `auxin-sdk` import, no network calls, no Solana. If the bridge crashes, network dies, or Solana is down — the watchdog still halts the arm.

The independence of the watchdog from the rest of the stack is the safety guarantee we present to regulators and hackathon judges.

---

## Status

Track B is gated on the Superteam hardware grant. The PyBullet digital twin (`/twin`) must be production-ready before this track begins. The ROS2 nodes are ready for deployment when the physical arm arrives.

---

## Structure

```
edge/
├── auxin_edge/
│   ├── telemetry_bridge_node.py   ROS2 → TelemetryFrame → auxin-sdk queue
│   ├── safety_watchdog_node.py    Independent torque monitor → /emergency_stop
│   └── ros2_source.py             ROS2Source(TelemetrySource) — ABC implementation
├── launch/
│   └── auxin_edge.launch.py       Launches both nodes together
└── systemd/
    ├── auxin-bridge.service        Bridge + telemetry node — auto-start on boot
    └── auxin-watchdog.service      Watchdog node — separate systemd unit
```

---

## Prerequisites

```bash
# Jetson: JetPack 6 + ROS2 Humble
sudo apt install ros-humble-desktop python3-colcon-common-extensions
source /opt/ros/humble/setup.bash

# Python deps (installed into ROS2 overlay)
pip install auxin-sdk   # telemetry_bridge_node only
```

---

## Build

```bash
cd edge
colcon build --symlink-install
source install/setup.bash
```

---

## Run

```bash
# Launch both nodes
ros2 launch auxin_edge auxin_edge.launch.py

# Or individually
ros2 run auxin_edge telemetry_bridge_node
ros2 run auxin_edge safety_watchdog_node

# Install systemd services (Jetson)
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl enable auxin-bridge auxin-watchdog
sudo systemctl start auxin-bridge auxin-watchdog
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ROS_DOMAIN_ID` | `0` | ROS2 domain isolation (change if multiple robots on LAN) |
| `JOINT_STATES_TOPIC` | `/joint_states` | Joint state topic (verify with `ros2 topic list`) |
| `TELEMETRY_RATE_HZ` | `2` | Throttled telemetry publish rate |
| `STALE_TIMEOUT_S` | `1.0` | Seconds before emitting `stale_telemetry` anomaly flag |
| `WATCHDOG_TORQUE_THRESHOLD` | `80.0` | Torque threshold in N·m; must match oracle (`GEMINI_API_KEY` torque_threshold) |
| `WATCHDOG_CONSECUTIVE_FRAMES` | `3` | Consecutive over-threshold frames before e-stop |
| `LOKI_URL` | — | Grafana Loki endpoint for remote log forwarding |

---

## Watchdog Independence Rule

`safety_watchdog_node.py` **must not**:
- Import `auxin_sdk` or any SDK module
- Make HTTP, WebSocket, or RPC calls
- Depend on the bridge process being alive

The watchdog's only dependencies are ROS2 itself and the arm's `/emergency_stop` service. This is not a style preference — it is the architectural guarantee that hardware safety does not depend on software infrastructure.

---

## How It Fits

```
Physical Arm (myCobot 280 / Franka Emika)
    ↓  /joint_states  (sensor_msgs/JointState)
telemetry_bridge_node → ROS2Source.queue → Bridge (auxin-sdk) → Solana + Dashboard
safety_watchdog_node  → /emergency_stop  (local, independent)
```

To run against the twin instead of the physical arm: set `AUXIN_SOURCE=twin` in the bridge process. The watchdog continues to run against the arm; only the telemetry source path changes. See the [root architecture diagram](../README.md#architecture).

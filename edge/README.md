# edge

ROS2 Python nodes for the NVIDIA Jetson Orin Nano. Bridges a physical robotic arm into the Auxin Automata SDK and independently monitors hardware safety — with no network dependency.

→ [Root README](../README.md)

---

## Purpose

Two nodes, two jobs, deliberately separate OS processes:

**`telemetry_bridge_node`** — subscribes to `/joint_states`, throttles to 2 Hz, converts to `TelemetryFrame`, and feeds the `ROS2Source` queue consumed by the Python bridge. It imports `auxin-sdk` and is network-aware.

**`safety_watchdog_node`** — subscribes to `/joint_states` at full rate, monitors effort values, and calls `/emergency_stop` if any torque exceeds the threshold for 3 consecutive frames. It is **completely independent**: no `auxin-sdk` import, no HTTP or WebSocket calls, no Solana. If the bridge crashes, the network dies, or Solana is down — the watchdog still halts the arm.

The watchdog's independence from the rest of the stack is the safety guarantee we present to regulators and hackathon judges. It is enforced structurally: imports are the unit of proof.

---

## Status

Track B is gated on the Superteam hardware grant. The PyBullet digital twin (`/twin`) is production-ready and carries the demo until the physical arm arrives. The ROS2 nodes are coded, tested offline, and ready to deploy when the arm is provisioned.

---

## Structure

```
edge/
├── auxin_edge/
│   ├── telemetry_bridge_node.py   ROS2 → TelemetryFrame → auxin-sdk queue
│   ├── safety_watchdog_node.py    Independent torque monitor → /emergency_stop
│   └── ros2_source.py             ROS2Source(TelemetrySource) — ABC implementation
├── launch/
│   └── auxin_edge.launch.py       Launches both nodes in a single process group
└── systemd/
    ├── auxin-bridge.service        SDK bridge + telemetry node (auto-start on boot)
    └── auxin-watchdog.service      Watchdog node — separate systemd unit, separate restart policy
```

---

## Prerequisites

```bash
# Jetson: JetPack 6 + ROS2 Humble
sudo apt install ros-humble-desktop python3-colcon-common-extensions
source /opt/ros/humble/setup.bash

# Python SDK (telemetry_bridge_node only — watchdog must not install this)
pip install auxin-sdk
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
# Both nodes together (development)
ros2 launch auxin_edge auxin_edge.launch.py

# Individually
ros2 run auxin_edge telemetry_bridge_node
ros2 run auxin_edge safety_watchdog_node

# Production — install systemd services on Jetson
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auxin-bridge auxin-watchdog
```

Verify watchdog heartbeat: `ros2 topic echo /auxin/watchdog_status`

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ROS_DOMAIN_ID` | `0` | ROS2 domain isolation (change if multiple robots on LAN) |
| `JOINT_STATES_TOPIC` | `/joint_states` | Joint state topic (confirm with `ros2 topic list`) |
| `TELEMETRY_RATE_HZ` | `2` | Throttled telemetry publish rate to SDK |
| `STALE_TIMEOUT_S` | `1.0` | Seconds without messages before emitting `stale_telemetry` anomaly flag |
| `WATCHDOG_TORQUE_THRESHOLD` | `80.0` | Torque threshold (N·m); must match `GEMINI_API_KEY` `torque_threshold` |
| `WATCHDOG_CONSECUTIVE_FRAMES` | `3` | Consecutive over-threshold frames before e-stop |
| `LOKI_URL` | — | Grafana Loki endpoint for remote log forwarding from Jetson |

---

## Watchdog Independence Rule

`safety_watchdog_node.py` must not:
- Import `auxin_sdk` or any SDK module
- Make HTTP, WebSocket, or RPC calls of any kind
- Depend on the bridge process being alive or reachable

Its only dependencies are `rclpy`, `sensor_msgs`, `std_msgs`, and `std_srvs`. This is not a style preference — it is the architectural guarantee that hardware safety does not depend on any software infrastructure outside the robot's local ROS2 graph.

---

## How It Fits

```
Physical Arm (myCobot 280 / Franka Emika)
    ↓  /joint_states  (sensor_msgs/JointState)
    ├── telemetry_bridge_node → ROS2Source.queue → Bridge (auxin-sdk) → Solana + Dashboard
    └── safety_watchdog_node → /emergency_stop  (local, independent of all network state)
```

To run against the twin instead: set `AUXIN_SOURCE=twin` in the bridge process. The watchdog continues monitoring the physical arm independently. See the [root architecture diagram](../README.md#architecture).

# edge

ROS2 Python nodes for the NVIDIA Jetson Orin Nano. Bridges a physical robotic arm into the Auxin Automata SDK, and independently monitors hardware safety with no network dependency.

→ [Root README](../README.md)

---

## Purpose

Two nodes, two responsibilities, deliberately separate OS processes:

**`telemetry_bridge_node`** — subscribes to `/joint_states`, throttles to 2 Hz, converts to `TelemetryFrame`, and feeds the `ROS2Source` queue consumed by the bridge. It imports `auxin-sdk` and is network-aware.

**`safety_watchdog_node`** — subscribes to `/joint_states` at full rate, monitors effort values, and calls `/emergency_stop` if any torque exceeds the threshold for 3 consecutive frames. It is **completely independent**: no `auxin-sdk` import, no HTTP or WebSocket calls, no Solana access. If the bridge crashes, the network dies, or Solana is down — the watchdog still halts the arm.

The watchdog's independence from the rest of the stack is a structural safety guarantee. Its dependency list is the proof: `rclpy`, `sensor_msgs`, `std_msgs`, `std_srvs`. Nothing else.

---

## Status

Track B is gated on the Superteam Ireland hardware grant. The PyBullet digital twin (`/twin`) is production-ready and carries the demo until hardware ships. These nodes are coded, tested offline, and ready to deploy when the arm is provisioned.

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
    ├── auxin-bridge.service        SDK bridge + telemetry node (boot-start)
    └── auxin-watchdog.service      Watchdog — separate unit, independent restart policy
```

---

## Prerequisites

```bash
# Jetson: JetPack 6 + ROS2 Humble
sudo apt install ros-humble-desktop python3-colcon-common-extensions
source /opt/ros/humble/setup.bash

# SDK (telemetry_bridge_node only — watchdog must not install this)
pip install auxin-sdk
```

---

## Build & Run

```bash
cd edge
colcon build --symlink-install
source install/setup.bash

# Both nodes together (development)
ros2 launch auxin_edge auxin_edge.launch.py

# Production — systemd
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auxin-bridge auxin-watchdog
```

Watchdog heartbeat: `ros2 topic echo /auxin/watchdog_status`

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ROS_DOMAIN_ID` | `0` | ROS2 domain isolation |
| `JOINT_STATES_TOPIC` | `/joint_states` | Joint state topic |
| `TELEMETRY_RATE_HZ` | `2` | Throttled SDK publish rate |
| `STALE_TIMEOUT_S` | `1.0` | Seconds without msgs before `stale_telemetry` anomaly flag |
| `WATCHDOG_TORQUE_THRESHOLD` | `80.0` | E-stop torque threshold (N·m) |
| `WATCHDOG_CONSECUTIVE_FRAMES` | `3` | Consecutive over-threshold frames before e-stop |

---

## Watchdog Independence Rule

`safety_watchdog_node.py` must never:
- Import `auxin_sdk` or any part of it
- Make HTTP, WebSocket, or RPC calls
- Depend on the bridge process being alive

This is enforced structurally. Its only imports are from the ROS2 standard library. The rule is documented in `CLAUDE.md` and applies permanently — not just during the hackathon.

---

## How It Fits

```
Physical Arm  →  /joint_states (sensor_msgs/JointState)
    ├── telemetry_bridge_node  →  ROS2Source  →  Bridge (auxin-sdk)  →  Solana + Dashboard
    └── safety_watchdog_node   →  /emergency_stop (local ROS2, network-independent)
```

To run against the twin instead of a physical arm: set `AUXIN_SOURCE=twin` in the bridge process. The watchdog continues monitoring the physical arm independently regardless. See the [root architecture diagram](../README.md#architecture).

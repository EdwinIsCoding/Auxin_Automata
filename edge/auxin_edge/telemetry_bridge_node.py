"""Telemetry bridge ROS2 node — /joint_states → TelemetryFrame → ROS2Source queue.

Subscribes to /joint_states with BEST_EFFORT QoS (matching typical robot drivers),
throttles to 2 Hz via a wall timer, and converts each sample into a TelemetryFrame
that the ROS2Source feeds into the auxin-sdk bridge.

Stale detection: if no /joint_states arrives within STALE_TIMEOUT_S (default 1 s),
the timer callback emits a frame with anomaly_flag ``stale_telemetry`` so the
bridge logs a compliance event.

Can be run standalone for testing:
    ros2 run auxin_edge telemetry_bridge_node

Or spun internally by ROS2Source for production use via AUXIN_SOURCE=ros2.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import JointState

from auxin_sdk.schema import TelemetryFrame

# QoS: keep only the latest message, BEST_EFFORT to match common robot drivers.
_JOINT_STATE_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)


class TelemetryBridgeNode(Node):  # type: ignore[misc]
    """
    ROS2 node that bridges /joint_states into TelemetryFrame objects.

    Parameters
    ----------
    topic
        Joint state topic name.
    rate_hz
        Timer frequency for emitting throttled frames.
    stale_timeout_s
        Seconds of silence on the joint state topic before flagging ``stale_telemetry``.
    frame_callback
        Called with each TelemetryFrame.  When driven by ROS2Source, this pushes
        into the asyncio queue.  When run standalone, defaults to logging.
    """

    def __init__(
        self,
        topic: str = "/joint_states",
        rate_hz: float = 2.0,
        stale_timeout_s: float = 1.0,
        frame_callback: Callable[[TelemetryFrame], None] | None = None,
    ) -> None:
        super().__init__("telemetry_bridge_node")

        self._frame_callback = frame_callback or self._default_callback
        self._stale_timeout_s = stale_timeout_s

        # Latest raw message — written by subscriber, read by timer.
        self._latest_msg: JointState | None = None
        self._last_msg_time: float = time.monotonic()
        self._prev_positions: list[float] | None = None

        # Subscribe at full rate; the timer below throttles output.
        self._sub = self.create_subscription(
            JointState,
            topic,
            self._joint_states_cb,
            qos_profile=_JOINT_STATE_QOS,
        )

        # Timer fires at rate_hz; each tick converts the latest message.
        period_s = 1.0 / rate_hz
        self._timer = self.create_wall_timer(period_s, self._timer_cb)

        self.get_logger().info(
            f"TelemetryBridgeNode started — topic={topic}  rate_hz={rate_hz}  "
            f"stale_timeout={stale_timeout_s}s"
        )

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _joint_states_cb(self, msg: JointState) -> None:
        """Store latest message; the timer will consume it at 2 Hz."""
        self._latest_msg = msg
        self._last_msg_time = time.monotonic()

    def _timer_cb(self) -> None:
        """Throttled emission: convert latest JointState → TelemetryFrame."""
        now_mono = time.monotonic()
        elapsed = now_mono - self._last_msg_time

        msg = self._latest_msg

        if msg is None or elapsed > self._stale_timeout_s:
            # No data received yet, or data is stale.
            self.get_logger().warning(
                f"No /joint_states for {elapsed:.1f}s — emitting stale_telemetry"
            )
            frame = self._build_stale_frame()
            self._frame_callback(frame)
            return

        frame = self._msg_to_frame(msg)
        self._frame_callback(frame)

    # ── Conversion ───────────────────────────────────────────────────────────

    def _msg_to_frame(self, msg: JointState) -> TelemetryFrame:
        """Convert a sensor_msgs/JointState into a TelemetryFrame."""
        positions = list(msg.position) if msg.position else [0.0]
        velocities = list(msg.velocity) if msg.velocity else [0.0] * len(positions)
        torques = list(msg.effort) if msg.effort else [0.0] * len(positions)

        # Anomaly detection: torque spike (matches watchdog threshold).
        anomaly_flags: list[str] = []
        if any(abs(t) > 80.0 for t in torques):
            anomaly_flags.append("torque_spike")

        # Simple EE pose proxy from first 3 joints (same convention as MockSource).
        n = len(positions)
        ee_pose = {
            "x": round(positions[0], 6) if n > 0 else 0.0,
            "y": round(positions[1], 6) if n > 1 else 0.0,
            "z": round(positions[2], 6) if n > 2 else 0.5,
        }

        frame = TelemetryFrame(
            timestamp=datetime.now(UTC),
            joint_positions=positions,
            joint_velocities=velocities,
            joint_torques=torques,
            end_effector_pose=ee_pose,
            anomaly_flags=anomaly_flags,
        )

        self._prev_positions = positions
        return frame

    def _build_stale_frame(self) -> TelemetryFrame:
        """Produce a frame with the stale_telemetry anomaly flag."""
        n = 6  # myCobot 280 has 6 DOF
        positions = self._prev_positions or [0.0] * n
        return TelemetryFrame(
            timestamp=datetime.now(UTC),
            joint_positions=positions,
            joint_velocities=[0.0] * len(positions),
            joint_torques=[0.0] * len(positions),
            end_effector_pose={"x": 0.0, "y": 0.0, "z": 0.5},
            anomaly_flags=["stale_telemetry"],
        )

    def _default_callback(self, frame: TelemetryFrame) -> None:
        """Standalone mode: log each frame for debugging."""
        self.get_logger().info(
            f"Frame: joints={len(frame.joint_positions)}  "
            f"flags={frame.anomaly_flags or 'nominal'}"
        )


# ── Standalone entry point ───────────────────────────────────────────────────


def main() -> None:
    rclpy.init()
    node = TelemetryBridgeNode()

    def _shutdown(sig: int, frame: object) -> None:
        node.get_logger().info("SIGINT received — shutting down")
        node.destroy_node()
        rclpy.try_shutdown()

    signal.signal(signal.SIGINT, _shutdown)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.try_shutdown()


if __name__ == "__main__":
    main()

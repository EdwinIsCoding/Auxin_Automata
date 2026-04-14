"""Safety watchdog — independent torque monitor with /emergency_stop capability.

INDEPENDENCE RULE (architectural invariant — never violate):
    - Must NOT import auxin_sdk or any SDK module.
    - Must NOT make any network calls (HTTP, WebSocket, RPC, Solana).
    - Purely local ROS2: subscribes /joint_states, calls /emergency_stop service.
    - Runs as a SEPARATE systemd unit (auxin-watchdog.service).

If the bridge crashes, the network dies, or Solana is down, this node STILL
halts the arm.  This independence IS the safety guarantee.

Trigger logic:
    If max(abs(effort)) > THRESHOLD for CONSECUTIVE_FRAMES consecutive messages,
    call the /emergency_stop service (std_srvs/Trigger).

Heartbeat:
    Publishes a Bool on /auxin/watchdog_status at 1 Hz.  True = armed and healthy.
"""

from __future__ import annotations

import os
import signal

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool
from std_srvs.srv import Trigger

# Environment-configurable thresholds (match sdk/.env.example defaults).
_TORQUE_THRESHOLD = float(os.environ.get("WATCHDOG_TORQUE_THRESHOLD", "80.0"))
_CONSECUTIVE_FRAMES = int(os.environ.get("WATCHDOG_CONSECUTIVE_FRAMES", "3"))

# Full-rate subscription — watchdog must see every message.
_JOINT_STATE_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)


class SafetyWatchdogNode(Node):  # type: ignore[misc]
    """
    Independent torque watchdog.  Zero SDK dependencies, zero network calls.

    Subscribes to ``/joint_states`` at full rate.  If
    ``max(abs(effort)) > threshold`` for ``consecutive_frames`` consecutive
    messages, calls the ``/emergency_stop`` service (std_srvs/Trigger).

    Publishes a heartbeat on ``/auxin/watchdog_status`` (std_msgs/Bool) at 1 Hz.
    """

    def __init__(self) -> None:
        super().__init__("safety_watchdog_node")

        self._threshold = _TORQUE_THRESHOLD
        self._consecutive_required = _CONSECUTIVE_FRAMES
        self._over_count = 0
        self._estop_triggered = False

        # ── Subscribe to /joint_states at full rate ──────────────────────────
        self._sub = self.create_subscription(
            JointState,
            "/joint_states",
            self._joint_states_cb,
            qos_profile=_JOINT_STATE_QOS,
        )

        # ── /emergency_stop service client ───────────────────────────────────
        self._estop_client = self.create_client(Trigger, "/emergency_stop")

        # ── Heartbeat publisher ──────────────────────────────────────────────
        self._heartbeat_pub = self.create_publisher(Bool, "/auxin/watchdog_status", 10)
        self._heartbeat_timer = self.create_wall_timer(1.0, self._heartbeat_cb)

        self.get_logger().info(
            f"SafetyWatchdogNode started — threshold={self._threshold} N*m  "
            f"consecutive={self._consecutive_required}"
        )

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _joint_states_cb(self, msg: JointState) -> None:
        """Check torque on every incoming /joint_states message."""
        if self._estop_triggered:
            return

        efforts = msg.effort
        if not efforts:
            self._over_count = 0
            return

        max_torque = max(abs(e) for e in efforts)

        if max_torque > self._threshold:
            self._over_count += 1
            self.get_logger().warning(
                f"Torque over threshold: {max_torque:.1f} N*m  "
                f"(count {self._over_count}/{self._consecutive_required})"
            )
            if self._over_count >= self._consecutive_required:
                self._trigger_estop(max_torque)
        else:
            # Reset counter — must be consecutive.
            self._over_count = 0

    def _heartbeat_cb(self) -> None:
        """Publish watchdog heartbeat.  True = armed and healthy."""
        msg = Bool()
        msg.data = not self._estop_triggered
        self._heartbeat_pub.publish(msg)

    # ── Emergency stop ───────────────────────────────────────────────────────

    def _trigger_estop(self, max_torque: float) -> None:
        """Call /emergency_stop service.  Fire-and-forget async call."""
        self._estop_triggered = True
        self.get_logger().fatal(
            f"E-STOP TRIGGERED — {max_torque:.1f} N*m exceeded {self._threshold} N*m "
            f"for {self._consecutive_required} consecutive frames"
        )

        if not self._estop_client.service_is_ready():
            self.get_logger().error(
                "/emergency_stop service not available — arm may not have stopped!"
            )
            return

        request = Trigger.Request()
        future = self._estop_client.call_async(request)
        future.add_done_callback(self._estop_done)

    def _estop_done(self, future: rclpy.task.Future) -> None:
        """Log result of /emergency_stop service call."""
        try:
            result = future.result()
            if result.success:
                self.get_logger().info(f"/emergency_stop succeeded: {result.message}")
            else:
                self.get_logger().error(f"/emergency_stop returned failure: {result.message}")
        except Exception as exc:
            self.get_logger().error(f"/emergency_stop call failed: {exc}")


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    rclpy.init()
    node = SafetyWatchdogNode()

    def _shutdown(sig: int, frame: object) -> None:
        node.get_logger().info("SIGINT received — shutting down watchdog")
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

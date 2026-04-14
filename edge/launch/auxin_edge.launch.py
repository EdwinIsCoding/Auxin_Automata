"""Launch file for both Auxin edge nodes.

    ros2 launch auxin_edge auxin_edge.launch.py

Launches:
    1. telemetry_bridge_node — /joint_states → TelemetryFrame → SDK bridge queue
    2. safety_watchdog_node  — independent torque monitor → /emergency_stop
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    telemetry_bridge = Node(
        package="auxin_edge",
        executable="telemetry_bridge_node",
        name="telemetry_bridge_node",
        output="screen",
        emulate_tty=True,
    )

    safety_watchdog = Node(
        package="auxin_edge",
        executable="safety_watchdog_node",
        name="safety_watchdog_node",
        output="screen",
        emulate_tty=True,
    )

    return LaunchDescription([telemetry_bridge, safety_watchdog])

"""Telemetry source abstractions.

Concrete implementations live in separate packages, selected at runtime via
the AUXIN_SOURCE environment variable:

    AUXIN_SOURCE=mock   → MockSource   (Phase 1B, /sdk)
    AUXIN_SOURCE=twin   → TwinSource   (Phase 1C, /twin)
    AUXIN_SOURCE=ros2   → ROS2Source   (Phase 2B, /edge)
"""

from .base import TelemetrySource

__all__ = ["TelemetrySource"]

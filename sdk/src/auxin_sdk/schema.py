"""TelemetryFrame — single source of truth for kinematic state across all hardware sources."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


class TelemetryFrame(BaseModel):
    """
    Canonical representation of one kinematic sample emitted by any telemetry source.

    All three sources — MockSource, TwinSource, ROS2Source — must produce
    TelemetryFrame objects that are schema-valid and mutually interchangeable.
    The bridge, hashing utility, and Solana client consume only this type.

    Fields
    ------
    timestamp
        UTC datetime of the sample (nanosecond precision supported).
    joint_positions
        Joint angles in radians, one element per DOF.
    joint_velocities
        Joint angular velocities in rad/s, same ordering as positions.
    joint_torques
        Joint torques in N·m.  Safety watchdog threshold is 80.0 N·m.
    end_effector_pose
        Free-form dict carrying the end-effector pose (x, y, z, roll, pitch, yaw
        or quaternion — source-dependent).
    anomaly_flags
        List of string tags describing detected anomalies, e.g. ``["torque_spike"]``.
        An empty list means the frame is nominal.
    """

    model_config = ConfigDict(populate_by_name=True)

    timestamp: datetime
    joint_positions: list[float]
    joint_velocities: list[float]
    joint_torques: list[float]
    end_effector_pose: dict[str, Any]
    anomaly_flags: list[str]

    @field_serializer("timestamp")
    def serialize_timestamp(self, v: datetime) -> str:
        """Serialise timestamp as ISO 8601 using Python's isoformat() — stable across Pydantic versions."""
        return v.isoformat()

    @field_validator("joint_positions", "joint_velocities", "joint_torques")
    @classmethod
    def must_be_non_empty(cls, v: list[float]) -> list[float]:
        if len(v) == 0:
            raise ValueError("joint arrays must not be empty")
        return v

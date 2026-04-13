"""Tests for auxin_sdk.schema.TelemetryFrame."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from auxin_sdk.schema import TelemetryFrame


# ── Valid construction ────────────────────────────────────────────────────────

def test_canonical_frame_is_valid(canonical_frame: TelemetryFrame) -> None:
    """The canonical fixture validates without errors and has correct field counts."""
    assert len(canonical_frame.joint_positions) == 6
    assert len(canonical_frame.joint_velocities) == 6
    assert len(canonical_frame.joint_torques) == 6
    assert canonical_frame.anomaly_flags == []


def test_anomalous_frame_carries_flag(anomalous_frame: TelemetryFrame) -> None:
    """An anomalous frame carries the expected flag and elevated torque."""
    assert "torque_spike" in anomalous_frame.anomaly_flags
    assert anomalous_frame.joint_torques[0] == 95.0


def test_minimal_valid_frame() -> None:
    """A frame with one joint and no anomalies is valid."""
    frame = TelemetryFrame(
        timestamp=datetime.now(timezone.utc),
        joint_positions=[0.0],
        joint_velocities=[0.0],
        joint_torques=[0.0],
        end_effector_pose={},
        anomaly_flags=[],
    )
    assert frame.joint_positions == [0.0]


# ── JSON round-trip ───────────────────────────────────────────────────────────

def test_json_round_trip_preserves_all_fields(canonical_frame: TelemetryFrame) -> None:
    """model_dump(mode='json') → model_validate recovers the original frame."""
    dumped = canonical_frame.model_dump(mode="json")
    restored = TelemetryFrame.model_validate(dumped)

    assert restored.joint_positions == canonical_frame.joint_positions
    assert restored.joint_velocities == canonical_frame.joint_velocities
    assert restored.joint_torques == canonical_frame.joint_torques
    assert restored.end_effector_pose == canonical_frame.end_effector_pose
    assert restored.anomaly_flags == canonical_frame.anomaly_flags


def test_json_serialisation_encodes_timestamp_as_iso(canonical_frame: TelemetryFrame) -> None:
    """Serialised JSON must represent the timestamp as an ISO 8601 string."""
    json_str = canonical_frame.model_dump_json()
    assert "2024-01-01" in json_str, "ISO date portion must appear in JSON output"


def test_model_dump_json_is_string(canonical_frame: TelemetryFrame) -> None:
    result = canonical_frame.model_dump_json()
    assert isinstance(result, str)
    assert len(result) > 0


# ── Validation errors ─────────────────────────────────────────────────────────

def test_empty_joint_positions_rejected() -> None:
    """Empty joint_positions must raise ValidationError."""
    with pytest.raises(ValidationError, match="must not be empty"):
        TelemetryFrame(
            timestamp=datetime.now(timezone.utc),
            joint_positions=[],
            joint_velocities=[0.0],
            joint_torques=[0.0],
            end_effector_pose={},
            anomaly_flags=[],
        )


def test_empty_joint_velocities_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        TelemetryFrame(
            timestamp=datetime.now(timezone.utc),
            joint_positions=[0.0],
            joint_velocities=[],
            joint_torques=[0.0],
            end_effector_pose={},
            anomaly_flags=[],
        )


def test_empty_joint_torques_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        TelemetryFrame(
            timestamp=datetime.now(timezone.utc),
            joint_positions=[0.0],
            joint_velocities=[0.0],
            joint_torques=[],
            end_effector_pose={},
            anomaly_flags=[],
        )


def test_missing_timestamp_rejected() -> None:
    """Missing timestamp must raise ValidationError."""
    with pytest.raises(ValidationError):
        TelemetryFrame(  # type: ignore[call-arg]
            joint_positions=[0.0],
            joint_velocities=[0.0],
            joint_torques=[0.0],
            end_effector_pose={},
            anomaly_flags=[],
        )


def test_invalid_timestamp_type_rejected() -> None:
    """A non-datetime timestamp value must raise ValidationError."""
    with pytest.raises(ValidationError):
        TelemetryFrame(
            timestamp="not-a-datetime",  # type: ignore[arg-type]
            joint_positions=[0.0],
            joint_velocities=[0.0],
            joint_torques=[0.0],
            end_effector_pose={},
            anomaly_flags=[],
        )

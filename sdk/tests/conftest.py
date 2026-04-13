"""Shared pytest fixtures and configuration for auxin-sdk tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from auxin_sdk.schema import TelemetryFrame


# ── Network test gating ───────────────────────────────────────────────────────

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests that require live Devnet access (costs SOL, needs network)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not config.getoption("--run-network"):
        skip = pytest.mark.skip(reason="Devnet test — run with --run-network to enable")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip)


# ── Canonical TelemetryFrame fixtures ────────────────────────────────────────
# These values are the ground truth for hashing determinism tests.
# Do NOT change them — existing cross-version hash assertions depend on them.

@pytest.fixture
def canonical_frame() -> TelemetryFrame:
    """
    Fixed, fully-specified TelemetryFrame used as the determinism baseline.

    All fields have known, stable values.  Any change to hashing.py that
    breaks the hash of this frame will be caught by test_hashing.py.
    """
    return TelemetryFrame(
        timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        joint_positions=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        joint_velocities=[0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
        joint_torques=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        end_effector_pose={
            "x": 0.5,
            "y": 0.0,
            "z": 0.3,
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
        },
        anomaly_flags=[],
    )


@pytest.fixture
def anomalous_frame(canonical_frame: TelemetryFrame) -> TelemetryFrame:
    """
    A variant of canonical_frame with a torque spike and anomaly flag injected.

    Represents the kind of frame that triggers the compliance log path in the bridge.
    """
    data = canonical_frame.model_dump()
    data["joint_torques"][0] = 95.0
    data["anomaly_flags"] = ["torque_spike"]
    return TelemetryFrame(**data)

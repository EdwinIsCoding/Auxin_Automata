"""Shared pytest fixtures and hooks for auxin-sdk tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from auxin_sdk.schema import TelemetryFrame


# ── CLI options ───────────────────────────────────────────────────────────────


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.network (requires Solana Devnet access).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not config.getoption("--run-network"):
        skip = pytest.mark.skip(reason="pass --run-network to run network tests")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip)


# ── Core fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def canonical_frame() -> TelemetryFrame:
    """
    Deterministic TelemetryFrame used for SHA-256 regression tests.

    The hash of this frame is pinned in test_hashing.py.  Do not change
    any field value without updating that pinned constant.
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
    """canonical_frame with joint_torques[0] = 95.0 and anomaly_flags = ['torque_spike']."""
    data = canonical_frame.model_dump()
    data["joint_torques"][0] = 95.0
    data["anomaly_flags"] = ["torque_spike"]
    return TelemetryFrame(**data)

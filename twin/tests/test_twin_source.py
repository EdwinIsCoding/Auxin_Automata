"""Smoke tests for TwinSource — verifies schema compliance and agnosticism contract.

All tests use rate_hz=0 so no anyio.sleep() is called and 100 frames complete
in milliseconds.  PyBullet runs in DIRECT (headless) mode.
"""

from __future__ import annotations

import math


from auxin_sdk.schema import TelemetryFrame
from twin import TwinSource
from twin.scene import NUM_ARM_JOINTS, RobotScene
from twin.trajectory import PickAndPlace


# ── Helpers ───────────────────────────────────────────────────────────────────


async def collect(source: TwinSource, n: int) -> list[TelemetryFrame]:
    """Collect exactly *n* frames from source.stream(), then stop."""
    frames: list[TelemetryFrame] = []
    async for frame in source.stream():
        frames.append(frame)
        if len(frames) >= n:
            break
    return frames


# ── Schema compliance ─────────────────────────────────────────────────────────


async def test_frames_validate_against_schema() -> None:
    """Every frame from TwinSource must be a valid TelemetryFrame."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 20)
    for frame in frames:
        assert isinstance(frame, TelemetryFrame)
        assert len(frame.joint_positions) == NUM_ARM_JOINTS
        assert len(frame.joint_velocities) == NUM_ARM_JOINTS
        assert len(frame.joint_torques) == NUM_ARM_JOINTS
        assert isinstance(frame.anomaly_flags, list)


async def test_100_frames_stream_cleanly() -> None:
    """100 frames stream without error — core smoke test for Phase 1C."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 100)
    assert len(frames) == 100


async def test_joint_count_matches_panda() -> None:
    """TwinSource yields 7-joint frames (Franka Panda has 7 DoF)."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 5)
    for frame in frames:
        assert len(frame.joint_positions) == 7
        assert len(frame.joint_velocities) == 7
        assert len(frame.joint_torques) == 7


async def test_eef_pose_contains_xyz() -> None:
    """end_effector_pose dict must contain x, y, z keys."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 3)
    for frame in frames:
        assert isinstance(frame.end_effector_pose, dict)
        assert "x" in frame.end_effector_pose
        assert "y" in frame.end_effector_pose
        assert "z" in frame.end_effector_pose


async def test_eef_pose_contains_quaternion() -> None:
    """end_effector_pose must also carry qx, qy, qz, qw from the link state."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 3)
    for frame in frames:
        pose = frame.end_effector_pose
        for key in ("qx", "qy", "qz", "qw"):
            assert key in pose, f"missing key '{key}' in end_effector_pose"


async def test_no_anomaly_flags_in_twin_source() -> None:
    """TwinSource does not inject anomalies — anomaly_flags must always be []."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 50)
    for frame in frames:
        assert frame.anomaly_flags == []


# ── Kinematics sanity ─────────────────────────────────────────────────────────


async def test_velocities_are_finite() -> None:
    """All joint velocities must be finite floating-point numbers."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 20)
    for frame in frames:
        for v in frame.joint_velocities:
            assert math.isfinite(v), f"non-finite velocity: {v}"


async def test_positions_are_finite() -> None:
    """All joint positions must be finite floating-point numbers."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 20)
    for frame in frames:
        for p in frame.joint_positions:
            assert math.isfinite(p), f"non-finite position: {p}"


async def test_positions_change_across_frames() -> None:
    """Joint positions must evolve as the trajectory drives the arm."""
    source = TwinSource(rate_hz=0)
    frames = await collect(source, 30)
    joint_0 = [f.joint_positions[0] for f in frames]
    assert len(set(round(p, 4) for p in joint_0)) > 1, (
        "joint 0 position did not change across 30 frames"
    )


# ── Agnosticism contract ──────────────────────────────────────────────────────


async def test_twin_source_is_interchangeable_with_mock_source() -> None:
    """
    TwinSource must be usable anywhere MockSource is used.

    This test calls only stream() and close() — the full agnosticism contract.
    No TwinSource-specific attributes are accessed.
    """
    from auxin_sdk.sources.base import TelemetrySource

    source: TelemetrySource = TwinSource(rate_hz=0)
    frames: list[TelemetryFrame] = []

    async for frame in source.stream():
        frames.append(frame)
        if len(frames) >= 10:
            break

    assert len(frames) == 10
    await source.close()


# ── Scene unit tests ──────────────────────────────────────────────────────────


def test_robot_scene_creates_and_closes() -> None:
    """RobotScene initialises PyBullet and disconnects without error."""
    scene = RobotScene(gui=False)
    try:
        positions, velocities, torques = scene.joint_states()
        assert len(positions) == NUM_ARM_JOINTS
        assert len(velocities) == NUM_ARM_JOINTS
        assert len(torques) == NUM_ARM_JOINTS
    finally:
        scene.close()


def test_robot_scene_eef_pose_structure() -> None:
    """eef_pose() returns a dict with the expected keys."""
    scene = RobotScene(gui=False)
    try:
        pose = scene.eef_pose()
        for key in ("x", "y", "z", "qx", "qy", "qz", "qw"):
            assert key in pose, f"missing key '{key}'"
    finally:
        scene.close()


def test_robot_scene_ik_returns_seven_joints() -> None:
    """ik() must return exactly NUM_ARM_JOINTS values."""
    scene = RobotScene(gui=False)
    try:
        result = scene.ik([0.4, 0.0, 0.6])
        assert len(result) == NUM_ARM_JOINTS
    finally:
        scene.close()


def test_robot_scene_capture_frame_returns_bytes() -> None:
    """capture_frame() must return non-empty JPEG bytes."""
    scene = RobotScene(gui=False)
    try:
        data = scene.capture_frame(width=160, height=120)
        assert isinstance(data, bytes)
        assert len(data) > 0
        # JPEG magic bytes: SOI marker
        assert data[:2] == b"\xff\xd8", "not a valid JPEG (missing SOI marker)"
    finally:
        scene.close()


# ── Trajectory unit tests ─────────────────────────────────────────────────────


def test_pick_and_place_cycles_waypoints() -> None:
    """PickAndPlace must cycle back to waypoint 0 after exhausting the list."""
    scene = RobotScene(gui=False)
    traj = PickAndPlace(steps_per_waypoint=2)
    try:
        seen: set[int] = set()
        for _ in range(100):
            traj.step(scene)
            seen.add(traj.waypoint_idx)
        # All 6 waypoints must be visited in 100 steps (2 steps each = 12 steps per cycle)
        assert seen == set(range(6)), f"not all waypoints visited: {seen}"
    finally:
        scene.close()


def test_pick_and_place_reset() -> None:
    """reset() must return the planner to waypoint 0."""
    scene = RobotScene(gui=False)
    traj = PickAndPlace(steps_per_waypoint=1)
    try:
        for _ in range(5):
            traj.step(scene)
        traj.reset()
        assert traj.waypoint_idx == 0
    finally:
        scene.close()

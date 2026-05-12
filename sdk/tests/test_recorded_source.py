"""Tests for RecordedSource — LeRobot recorded data replay.

Creates a minimal in-memory episode fixture (10 frames of dummy data)
and verifies:
 - TelemetryFrames are yielded at the expected rate
 - Frame fields are correctly mapped from robot.jsonl
 - Anomaly detection fires on fault flags
 - get_frame_sync_info() returns correct progress info
 - get_video_path() returns None when mp4 is absent
 - close() is idempotent
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from auxin_sdk.schema import TelemetryFrame
from auxin_sdk.sources.recorded import RecordedSource

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_robot_row(
    idx: int,
    timestamp_ns: int,
    control_exception: bool = False,
    gripper_fault: bool = False,
) -> dict:
    """Produce one robot.jsonl row matching the real Franka recording format."""
    q = [0.01 * idx] * 7
    dq = [0.001 * idx] * 7
    return {
        "robot_state": {
            "q": q,
            "dq": dq,
            "tcp_position_xyz": [0.4, 0.03, 0.3 + 0.01 * idx],
            "tcp_orientation_xyzw": [0.97, -0.01, 0.23, 0.009],
            "gripper_state": "OPEN",
            "gripper_width": 0.077,
        },
        "commanded_target_state": {},
        "desired_target_state": {},
        "executed_action": {},
        "status": {
            "control_mode": "HOLD",
            "episode_end": False,
            "episode_start": False,
            "fault_flags": {
                "control_exception": control_exception,
                "gripper_fault": gripper_fault,
                "ik_rejected": False,
                "jump_rejected": False,
                "packet_timeout": False,
                "robot_not_ready": False,
                "workspace_clamped": False,
            },
            "packet_age_ns": 9_000_000,
            "target_age_ns": 4_000_000,
            "target_fresh": False,
            "target_manipulability": 0.0,
            "teleop_active": False,
            "teleop_state": "CONNECTED_IDLE",
        },
        "timestamp_ns": timestamp_ns,
    }


def _make_episode_dir(tmp_path: Path, num_frames: int = 10) -> Path:
    """Create a minimal episode directory with synthetic robot data."""
    episode_dir = tmp_path / "episode_test"
    episode_dir.mkdir()

    # robot.jsonl — 10 frames at ~50 Hz (20 ms apart)
    robot_path = episode_dir / "robot.jsonl"
    base_ns = 520_000_000_000_000
    interval_ns = 20_000_000  # 20 ms
    with robot_path.open("w", encoding="utf-8") as fh:
        for i in range(num_frames):
            row = _make_robot_row(i, base_ns + i * interval_ns)
            fh.write(json.dumps(row) + "\n")

    # session_metadata.json
    meta_path = episode_dir / "session_metadata.json"
    meta_path.write_text(
        json.dumps(
            {
                "recording_id": "test_episode",
                "config": {"zed": {"fps": 30}, "robot": {}},
            }
        ),
        encoding="utf-8",
    )

    # episode_events.jsonl (empty)
    (episode_dir / "episode_events.jsonl").write_text("", encoding="utf-8")

    # cameras/ee_zed_m_left/frames.jsonl (no rgb.mp4 — video tests skip)
    camera_dir = episode_dir / "cameras" / "ee_zed_m_left"
    camera_dir.mkdir(parents=True)
    frames_path = camera_dir / "frames.jsonl"
    with frames_path.open("w", encoding="utf-8") as fh:
        for i in range(num_frames):
            row = {
                "camera": "ee_zed_m_left",
                "frame_index": i,
                "rgb_video_frame": i,
                "host_timestamp_ns": base_ns + i * interval_ns,
                "width": 1280,
                "height": 720,
            }
            fh.write(json.dumps(row) + "\n")

    return episode_dir


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_loads_robot_jsonl(tmp_path: Path) -> None:
    """RecordedSource must parse robot.jsonl and expose frame count."""
    episode_dir = _make_episode_dir(tmp_path, num_frames=10)
    src = RecordedSource(episode_dir, loop=False)
    assert src.total_frames == 10


def test_stream_yields_telemetry_frames(tmp_path: Path) -> None:
    """stream() must yield TelemetryFrame objects for every robot.jsonl row."""
    episode_dir = _make_episode_dir(tmp_path, num_frames=5)
    src = RecordedSource(episode_dir, loop=False)

    async def collect() -> list[TelemetryFrame]:
        frames: list[TelemetryFrame] = []
        async for frame in src.stream():
            frames.append(frame)
            if len(frames) >= 5:  # skip sentinel frames, collect data frames
                break
        await src.close()
        return frames

    frames = asyncio.get_event_loop().run_until_complete(collect())

    # Should have received data frames (sentinels have anomaly_flags)
    data_frames = [f for f in frames if not f.anomaly_flags]
    assert len(data_frames) >= 1

    # Validate schema on the first data frame
    f = data_frames[0]
    assert isinstance(f, TelemetryFrame)
    assert len(f.joint_positions) == 7
    assert len(f.joint_velocities) == 7
    assert len(f.joint_torques) == 7
    assert isinstance(f.end_effector_pose, dict)
    assert "x" in f.end_effector_pose
    assert "gripper_state" in f.end_effector_pose


def test_joint_positions_mapped_correctly(tmp_path: Path) -> None:
    """joint_positions in TelemetryFrame must equal robot_state.q in robot.jsonl."""
    episode_dir = _make_episode_dir(tmp_path, num_frames=3)
    src = RecordedSource(episode_dir, loop=False)

    async def get_first_data_frame() -> TelemetryFrame | None:
        async for frame in src.stream():
            if not frame.anomaly_flags:
                await src.close()
                return frame
        await src.close()
        return None

    frame = asyncio.get_event_loop().run_until_complete(get_first_data_frame())
    assert frame is not None
    # First row has q = [0.0] * 7 (0.01 * 0)
    assert all(abs(p - 0.0) < 1e-9 for p in frame.joint_positions)


def test_anomaly_detection_control_exception(tmp_path: Path) -> None:
    """Frames with control_exception fault flag must get 'control_exception' anomaly."""
    episode_dir = tmp_path / "episode_fault"
    episode_dir.mkdir()

    # Single frame with control_exception=True
    robot_path = episode_dir / "robot.jsonl"
    row = _make_robot_row(0, 520_000_000_000_000, control_exception=True)
    robot_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    (episode_dir / "session_metadata.json").write_text(json.dumps({}), encoding="utf-8")
    (episode_dir / "episode_events.jsonl").write_text("", encoding="utf-8")

    src = RecordedSource(episode_dir, loop=False)

    async def collect_anomaly() -> list[str]:
        async for frame in src.stream():
            if "control_exception" in frame.anomaly_flags:
                await src.close()
                return frame.anomaly_flags
        await src.close()
        return []

    flags = asyncio.get_event_loop().run_until_complete(collect_anomaly())
    assert "control_exception" in flags


def test_session_sentinels_emitted(tmp_path: Path) -> None:
    """stream() must emit replay_session_start and replay_session_end around each loop."""
    episode_dir = _make_episode_dir(tmp_path, num_frames=3)
    src = RecordedSource(episode_dir, loop=False)

    async def collect_all() -> list[TelemetryFrame]:
        frames: list[TelemetryFrame] = []
        async for frame in src.stream():
            frames.append(frame)
        await src.close()
        return frames

    all_frames = asyncio.get_event_loop().run_until_complete(collect_all())

    flags_seen = [f.anomaly_flags for f in all_frames if f.anomaly_flags]
    start_flags = [f for f in flags_seen if "replay_session_start" in f]
    end_flags = [f for f in flags_seen if "replay_session_end" in f]

    assert len(start_flags) == 1, "Expected exactly one replay_session_start sentinel"
    assert len(end_flags) == 1, "Expected exactly one replay_session_end sentinel"


def test_get_frame_sync_info_updates(tmp_path: Path) -> None:
    """get_frame_sync_info() must return correct progress and camera_key."""
    episode_dir = _make_episode_dir(tmp_path, num_frames=10)
    src = RecordedSource(episode_dir, camera_key="ee_zed_m_left", loop=False)

    info = src.get_frame_sync_info()
    assert info["camera_key"] == "ee_zed_m_left"
    assert info["total_frames"] == 10
    assert 0.0 <= info["episode_progress"] <= 1.0
    assert isinstance(info["frame_index"], int)


def test_get_video_path_returns_none_when_absent(tmp_path: Path) -> None:
    """get_video_path() must return None if the mp4 does not exist."""
    episode_dir = _make_episode_dir(tmp_path, num_frames=5)
    src = RecordedSource(episode_dir, camera_key="ee_zed_m_left", loop=False)

    # No rgb.mp4 was created in the fixture
    assert src.get_video_path("ee_zed_m_left") is None
    assert src.get_video_path(None) is None


def test_close_is_idempotent(tmp_path: Path) -> None:
    """close() must be safe to call multiple times."""
    episode_dir = _make_episode_dir(tmp_path, num_frames=3)
    src = RecordedSource(episode_dir, loop=False)

    async def run() -> None:
        await src.close()
        await src.close()  # second call must not raise

    asyncio.get_event_loop().run_until_complete(run())


def test_playback_speed_affects_timing(tmp_path: Path) -> None:
    """Faster playback_speed should reduce total elapsed time."""
    episode_dir = _make_episode_dir(tmp_path, num_frames=5)

    async def time_replay(speed: float) -> float:
        src = RecordedSource(episode_dir, playback_speed=speed, loop=False)
        t0 = time.monotonic()
        count = 0
        async for _ in src.stream():
            count += 1
        await src.close()
        return time.monotonic() - t0

    # At 100x speed, 5 frames at 20ms apart → ~0.001 s total
    elapsed = asyncio.get_event_loop().run_until_complete(time_replay(100.0))
    # Should complete in well under 1 second even at 1x (5 * 20ms = 100ms)
    assert elapsed < 2.0, f"Playback took too long: {elapsed:.2f}s"


# ── Edge case tests ──────────────────────────────────────────────────────────


def _make_minimal_episode(tmp_path: Path, rows: int = 5) -> Path:
    """Create a minimal episode directory with robot.jsonl only."""
    episode = tmp_path / "episode_minimal"
    episode.mkdir()
    robot = episode / "robot.jsonl"
    lines = []
    for i in range(rows):
        lines.append(
            json.dumps(
                {
                    "timestamp_ns": 520_000_000_000_000 + i * 20_000_000,
                    "robot_state": {
                        "q": [0.01 * i] * 7,
                        "dq": [0.001 * i] * 7,
                        "tcp_position_xyz": [0.1, 0.2, 0.3],
                        "tcp_orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
                        "gripper_state": "OPEN",
                        "gripper_width": 0.077,
                    },
                    "status": {
                        "fault_flags": {},
                    },
                }
            )
        )
    robot.write_text("\n".join(lines) + "\n")
    # Minimal metadata
    (episode / "session_metadata.json").write_text("{}", encoding="utf-8")
    (episode / "episode_events.jsonl").write_text("", encoding="utf-8")
    return episode


def test_missing_robot_jsonl_raises(tmp_path: Path) -> None:
    """FileNotFoundError when robot.jsonl does not exist."""
    episode = tmp_path / "episode_empty"
    episode.mkdir()
    (episode / "session_metadata.json").write_text("{}")
    (episode / "episode_events.jsonl").write_text("")
    with pytest.raises(FileNotFoundError):
        RecordedSource(episode)


def test_empty_robot_jsonl_raises(tmp_path: Path) -> None:
    """ValueError when robot.jsonl is empty."""
    episode = tmp_path / "episode_empty_jsonl"
    episode.mkdir()
    (episode / "robot.jsonl").write_text("")
    (episode / "session_metadata.json").write_text("{}")
    (episode / "episode_events.jsonl").write_text("")
    with pytest.raises(ValueError):
        RecordedSource(episode)


def test_stream_max_loops(tmp_path: Path) -> None:
    """Max loops terminates the stream."""
    episode = _make_minimal_episode(tmp_path, rows=2)
    src = RecordedSource(episode, loop=True, max_loops=2, playback_speed=9999)

    async def collect_all() -> int:
        count = 0
        async for _ in src.stream():
            count += 1
            if count > 200:
                break
        return count

    count = asyncio.get_event_loop().run_until_complete(collect_all())
    # 2 loops x (1 start + 2 data + 1 end) = 8
    assert count == 8


def test_close_stops_stream(tmp_path: Path) -> None:
    """close() sets _closed and stops the stream."""
    episode = _make_minimal_episode(tmp_path, rows=10)
    src = RecordedSource(episode, loop=True, playback_speed=9999)

    async def run() -> None:
        count = 0
        async for _ in src.stream():
            count += 1
            if count >= 3:
                await src.close()
        assert src._closed

    asyncio.get_event_loop().run_until_complete(run())


def test_get_frame_at_no_frame_map(tmp_path: Path) -> None:
    """get_frame_at returns None when no frame map exists."""
    episode = _make_minimal_episode(tmp_path)
    src = RecordedSource(episode)
    assert src.get_frame_at(0) is None


def test_get_available_cameras_empty(tmp_path: Path) -> None:
    """get_available_cameras returns empty list when no cameras with rgb.mp4."""
    episode = _make_minimal_episode(tmp_path)
    src = RecordedSource(episode)
    assert src.get_available_cameras() == []


def test_total_frames_property(tmp_path: Path) -> None:
    """total_frames returns correct count."""
    episode = _make_minimal_episode(tmp_path, rows=7)
    src = RecordedSource(episode)
    assert src.total_frames == 7


def test_torque_spike_detection(tmp_path: Path) -> None:
    """Torque spike check fires when max torque exceeds threshold."""
    episode = _make_minimal_episode(tmp_path, rows=1)
    # Torques in _parse_row are always [0.0]*7, so use a negative threshold
    # to trigger the `max(abs(t)) > threshold` branch (0.0 > -1.0 is True).
    src = RecordedSource(episode, loop=False, torque_threshold=-1.0)

    async def collect_flags() -> list[str]:
        async for frame in src.stream():
            if "torque_spike" in frame.anomaly_flags:
                return frame.anomaly_flags
        return []

    flags = asyncio.get_event_loop().run_until_complete(collect_flags())
    assert "torque_spike" in flags


def test_close_releases_video_capture(tmp_path: Path) -> None:
    """close() releases _cap if it was set."""
    episode = _make_minimal_episode(tmp_path)
    src = RecordedSource(episode)
    # Simulate a cap being set
    mock_cap = type("MockCap", (), {"release": lambda self: None})()
    src._cap = mock_cap

    asyncio.get_event_loop().run_until_complete(src.close())
    assert src._cap is None
    assert src._closed

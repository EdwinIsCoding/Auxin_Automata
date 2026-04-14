"""Tests for MockSource, ReplaySource, and the fixture sampler."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from auxin_sdk.fixtures import all_fixture_images, sample_workspace_image
from auxin_sdk.hashing import sha256_hex
from auxin_sdk.schema import TelemetryFrame
from auxin_sdk.sources.mock import (
    _TORQUE_SPIKE_VALUE,
    MockSource,
    ReplaySource,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


async def collect(source: MockSource | ReplaySource, n: int) -> list[TelemetryFrame]:
    """Collect exactly *n* frames from *source.stream()*, then stop."""
    frames: list[TelemetryFrame] = []
    async for frame in source.stream():
        frames.append(frame)
        if len(frames) >= n:
            break
    return frames


# ── Schema compliance ─────────────────────────────────────────────────────────


async def test_frames_validate_against_schema() -> None:
    """Every frame yielded by MockSource must be a valid TelemetryFrame."""
    source = MockSource(rate_hz=0, seed=0)
    frames = await collect(source, 20)
    for frame in frames:
        assert isinstance(frame, TelemetryFrame)
        assert len(frame.joint_positions) == 6
        assert len(frame.joint_velocities) == 6
        assert len(frame.joint_torques) == 6
        assert isinstance(frame.anomaly_flags, list)


async def test_custom_num_joints() -> None:
    """num_joints parameter is reflected in every frame."""
    source = MockSource(rate_hz=0, num_joints=3, seed=0)
    frames = await collect(source, 5)
    for frame in frames:
        assert len(frame.joint_positions) == 3
        assert len(frame.joint_torques) == 3


async def test_nominal_frames_have_no_anomaly_flags() -> None:
    """Frames between anomalies must have empty anomaly_flags."""
    # Use a large anomaly_every so we can collect purely nominal frames
    source = MockSource(rate_hz=0, anomaly_every=50, seed=0)
    frames = await collect(source, 10)  # well before first anomaly
    for frame in frames:
        assert frame.anomaly_flags == []


async def test_end_effector_pose_is_dict() -> None:
    source = MockSource(rate_hz=0, seed=0)
    frames = await collect(source, 3)
    for frame in frames:
        assert isinstance(frame.end_effector_pose, dict)
        assert "x" in frame.end_effector_pose


# ── Kinematics ────────────────────────────────────────────────────────────────


async def test_velocities_are_finite() -> None:
    """All velocity values must be finite numbers."""
    import math

    source = MockSource(rate_hz=10.0, seed=0)
    frames = await collect(source, 5)
    for frame in frames:
        for v in frame.joint_velocities:
            assert math.isfinite(v)


async def test_zero_rate_hz_gives_zero_velocities_on_first_frame() -> None:
    """With rate_hz=0, dt=0, so frame 0 velocities must be zero."""
    source = MockSource(rate_hz=0, seed=0)
    frames = await collect(source, 1)
    assert all(v == 0.0 for v in frames[0].joint_velocities)


async def test_positions_change_across_frames() -> None:
    """Joint positions must not be constant (sin drift must be visible)."""
    source = MockSource(rate_hz=10.0, seed=0)
    frames = await collect(source, 20)
    pos_0 = [f.joint_positions[0] for f in frames]
    assert len(set(round(p, 4) for p in pos_0)) > 1, "joint 0 position did not change"


# ── Anomaly injection ─────────────────────────────────────────────────────────


async def test_anomaly_appears_within_expected_window() -> None:
    """
    With default anomaly_every=12, the first anomaly must appear by frame 15
    (anomaly_every + max_jitter = 12 + 3 = 15, 0-indexed → frame ≤ 15).
    """
    source = MockSource(rate_hz=0, anomaly_every=12, seed=0)
    frames = await collect(source, 16)
    anomaly_indices = [i for i, f in enumerate(frames) if f.anomaly_flags]
    assert len(anomaly_indices) >= 1, "no anomaly within first 16 frames"
    assert anomaly_indices[0] <= 15


async def test_anomaly_torque_spike_reaches_threshold() -> None:
    """The spiked torque value must equal _TORQUE_SPIKE_VALUE (95.0 N·m)."""
    source = MockSource(rate_hz=0, seed=0)
    frames = await collect(source, 20)
    anomalous = [f for f in frames if f.anomaly_flags]
    assert len(anomalous) >= 1
    for frame in anomalous:
        assert _TORQUE_SPIKE_VALUE in frame.joint_torques, (
            f"expected {_TORQUE_SPIKE_VALUE} in torques, got {frame.joint_torques}"
        )


async def test_anomaly_flag_is_torque_spike() -> None:
    """Anomaly frames must carry exactly the 'torque_spike' flag."""
    source = MockSource(rate_hz=0, seed=0)
    frames = await collect(source, 20)
    for frame in frames:
        if frame.anomaly_flags:
            assert "torque_spike" in frame.anomaly_flags


async def test_anomalies_recur() -> None:
    """Multiple anomalies appear across a longer sequence."""
    source = MockSource(rate_hz=0, anomaly_every=6, seed=42)
    frames = await collect(source, 60)
    anomaly_count = sum(1 for f in frames if f.anomaly_flags)
    assert anomaly_count >= 4, f"expected ≥4 anomalies in 60 frames, got {anomaly_count}"


async def test_anomaly_spacing_respects_jitter() -> None:
    """Consecutive anomalies are separated by anomaly_every ± 3 frames."""
    every = 10
    source = MockSource(rate_hz=0, anomaly_every=every, seed=7)
    frames = await collect(source, 100)
    anomaly_indices = [i for i, f in enumerate(frames) if f.anomaly_flags]
    assert len(anomaly_indices) >= 2
    for a, b in zip(anomaly_indices, anomaly_indices[1:], strict=False):
        gap = b - a
        assert every - 3 <= gap <= every + 3, f"gap {gap} is outside [{every - 3}, {every + 3}]"


# ── Seeded reproducibility ────────────────────────────────────────────────────


async def test_same_seed_produces_same_joint_positions() -> None:
    """Two MockSources with identical seeds must produce identical joint positions."""
    s1 = MockSource(rate_hz=0, seed=99)
    s2 = MockSource(rate_hz=0, seed=99)
    f1 = await collect(s1, 15)
    f2 = await collect(s2, 15)
    for a, b in zip(f1, f2, strict=True):
        assert a.joint_positions == b.joint_positions
        assert a.joint_torques == b.joint_torques
        assert a.anomaly_flags == b.anomaly_flags


async def test_different_seeds_produce_different_sequences() -> None:
    """Different seeds must produce different joint-position sequences."""
    f1 = await collect(MockSource(rate_hz=0, seed=1), 10)
    f2 = await collect(MockSource(rate_hz=0, seed=2), 10)
    positions_match = all(
        a.joint_positions == b.joint_positions for a, b in zip(f1, f2, strict=False)
    )
    assert not positions_match, "different seeds produced identical sequences"


# ── Recording ─────────────────────────────────────────────────────────────────


async def test_record_to_creates_jsonl_file(tmp_path: Path) -> None:
    """record_to() writes a non-empty JSONL file."""
    record_path = tmp_path / "session.jsonl"
    source = MockSource(rate_hz=0, seed=0)

    with source.record_to(record_path) as s:
        await collect(s, 5)

    assert record_path.exists()
    lines = [ln for ln in record_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 5


async def test_record_to_each_line_is_valid_json(tmp_path: Path) -> None:
    """Every line in the recording must be valid JSON parseable as TelemetryFrame."""
    import json

    record_path = tmp_path / "session.jsonl"
    source = MockSource(rate_hz=0, seed=0)

    with source.record_to(record_path) as s:
        await collect(s, 8)

    for line in record_path.read_text().splitlines():
        if line.strip():
            data = json.loads(line)
            frame = TelemetryFrame.model_validate(data)
            assert isinstance(frame, TelemetryFrame)


async def test_record_to_creates_parent_dirs(tmp_path: Path) -> None:
    record_path = tmp_path / "nested" / "dir" / "session.jsonl"
    source = MockSource(rate_hz=0, seed=0)
    with source.record_to(record_path) as s:
        await collect(s, 2)
    assert record_path.exists()


async def test_record_file_closed_after_context_exit(tmp_path: Path) -> None:
    """The recording file handle must be closed when the context manager exits."""
    record_path = tmp_path / "session.jsonl"
    source = MockSource(rate_hz=0, seed=0)
    with source.record_to(record_path) as s:
        await collect(s, 3)
    assert source._record_fh is None


# ── ReplaySource — bit-identical ──────────────────────────────────────────────


async def test_replay_source_frame_count_matches_recording(tmp_path: Path) -> None:
    """ReplaySource yields exactly as many frames as were recorded."""
    record_path = tmp_path / "session.jsonl"
    source = MockSource(rate_hz=0, seed=0)

    with source.record_to(record_path) as s:
        original = await collect(s, 12)

    replay = ReplaySource(record_path, rate_hz=0)
    replayed = await collect(replay, 9999)  # drain completely

    assert len(replayed) == len(original)


async def test_replay_source_hashes_match_recorded_hashes(tmp_path: Path) -> None:
    """
    Each replayed frame must hash identically to the original.

    This is the core guarantee: the compliance log hash written on-chain during
    recording can be independently verified by replaying the JSONL session.
    """
    record_path = tmp_path / "session.jsonl"
    source = MockSource(rate_hz=0, seed=42)

    with source.record_to(record_path) as s:
        original = await collect(s, 20)

    replay = ReplaySource(record_path, rate_hz=0)
    replayed = await collect(replay, 9999)

    assert len(replayed) == len(original)
    for i, (orig, rep) in enumerate(zip(original, replayed, strict=True)):
        orig_hash = sha256_hex(orig)
        rep_hash = sha256_hex(rep)
        assert orig_hash == rep_hash, (
            f"frame {i}: hash mismatch\n  original: {orig_hash}\n  replayed: {rep_hash}"
        )


async def test_replay_includes_anomalous_frames(tmp_path: Path) -> None:
    """Replayed anomalous frames must preserve torque spike and flag."""
    record_path = tmp_path / "session.jsonl"
    source = MockSource(rate_hz=0, seed=0)

    with source.record_to(record_path) as s:
        original = await collect(s, 20)

    replay = ReplaySource(record_path, rate_hz=0)
    replayed = await collect(replay, 9999)

    orig_anomalous = [f for f in original if f.anomaly_flags]
    rep_anomalous = [f for f in replayed if f.anomaly_flags]
    assert len(orig_anomalous) == len(rep_anomalous)
    for o, r in zip(orig_anomalous, rep_anomalous, strict=True):
        assert o.anomaly_flags == r.anomaly_flags
        assert o.joint_torques == r.joint_torques


# ── Fixture sampler ───────────────────────────────────────────────────────────


def test_sample_workspace_image_returns_path_and_label() -> None:
    path, label = sample_workspace_image()
    assert isinstance(path, Path)
    assert label in ("clear", "obstacle")


def test_sample_workspace_image_file_exists() -> None:
    path, _ = sample_workspace_image()
    assert path.exists(), f"fixture image not found: {path}"


def test_sample_workspace_image_label_consistent_with_filename() -> None:
    """Filename prefix must agree with the label from labels.json."""
    for _ in range(10):
        path, label = sample_workspace_image()
        assert path.name.startswith(label), (
            f"label '{label}' inconsistent with filename '{path.name}'"
        )


def test_sample_workspace_image_seeded_reproducible() -> None:
    """Seeded sampler must return the same image on repeated calls."""
    results = [sample_workspace_image(rng=random.Random(0)) for _ in range(5)]
    # All calls with fresh seed=0 must pick the same image
    assert all(r[0] == results[0][0] for r in results)


def test_all_fixture_images_returns_20_entries() -> None:
    pairs = all_fixture_images()
    assert len(pairs) == 20


def test_all_fixture_images_balanced_labels() -> None:
    """Fixture set must have exactly 10 clear and 10 obstacle images."""
    pairs = all_fixture_images()
    clear = [p for p in pairs if p[1] == "clear"]
    obstacle = [p for p in pairs if p[1] == "obstacle"]
    assert len(clear) == 10
    assert len(obstacle) == 10


def test_all_fixture_images_all_exist() -> None:
    for path, _ in all_fixture_images():
        assert path.exists(), f"fixture missing: {path}"


# ── Constructor validation ────────────────────────────────────────────────────


def test_num_joints_zero_raises() -> None:
    with pytest.raises(ValueError, match="num_joints"):
        MockSource(num_joints=0)


def test_anomaly_every_too_small_raises() -> None:
    with pytest.raises(ValueError, match="anomaly_every"):
        MockSource(anomaly_every=2)

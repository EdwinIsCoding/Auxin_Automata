"""MockSource — synthetic kinematic telemetry; no hardware required.

Joint positions drift via per-joint sin/cos + Gaussian noise.
Velocities are the numerical derivative of consecutive positions.
Torques are a constant baseline + noise, with periodic injected spikes.

AUXIN_SOURCE=mock selects this source in the bridge.
"""

from __future__ import annotations

import math
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

import anyio
import structlog

from ..schema import TelemetryFrame
from .base import TelemetrySource

log = structlog.get_logger(__name__)

# Kinematics constants
_POSITION_AMPLITUDE = 0.5  # radians
_POSITION_FREQ = 0.3  # rad/s (slow drift, visually convincing)
_POSITION_NOISE_STD = 0.02  # radians
_BASELINE_TORQUE = 5.0  # N·m
_TORQUE_NOISE_STD = 0.5  # N·m
_TORQUE_SPIKE_VALUE = 95.0  # N·m  (matches watchdog threshold of 80.0)


class MockSource(TelemetrySource):
    """
    Synthetic kinematic telemetry source — no hardware or simulation required.

    Designed to be a drop-in replacement for TwinSource and ROS2Source: the bridge
    and all downstream code call only ``stream()`` and ``close()``.

    AUXIN_SOURCE=mock  →  this class is instantiated by the bridge entrypoint.

    Recording
    ---------
    Wrap the source with ``record_to(path)`` to persist a session as JSONL::

        with mock.record_to("session.jsonl") as source:
            async for frame in source.stream():
                ...

    Replay the session deterministically with :class:`ReplaySource`.
    """

    def __init__(
        self,
        rate_hz: float = 10.0,
        num_joints: int = 6,
        anomaly_every: int = 12,
        seed: int | None = None,
    ) -> None:
        """
        Parameters
        ----------
        rate_hz
            Frames yielded per second.  Use ``0`` in tests to skip all sleeps.
        num_joints
            Degrees of freedom.  Must be ≥ 1.
        anomaly_every
            Base frame interval between torque-spike anomalies.  Actual interval is
            ``anomaly_every + randint(-3, 3)`` so injections are not perfectly periodic.
        seed
            Fix the RNG for reproducible joint-position sequences (timestamps still
            use wall-clock time; replay them via ReplaySource for full determinism).
        """
        if num_joints < 1:
            raise ValueError(f"num_joints must be ≥ 1, got {num_joints}")
        if anomaly_every < 4:
            raise ValueError(
                f"anomaly_every must be ≥ 4 (needs ±3 jitter room), got {anomaly_every}"
            )

        self._rate_hz = rate_hz
        self._num_joints = num_joints
        self._anomaly_every = anomaly_every
        self._rng = random.Random(seed)
        self._record_fh: IO[str] | None = None
        self._closed = False

        # Spread per-joint phase offsets evenly across [0, 2π) so joints
        # don't all reach their maximum simultaneously.
        self._phases = [j * (2.0 * math.pi / num_joints) for j in range(num_joints)]

    # ── Recording API ─────────────────────────────────────────────────────────

    def record_to(self, path: Path | str) -> _RecordCtx:
        """
        Return a sync context manager that records every yielded frame to *path* (JSONL).

        Each line is one ``TelemetryFrame.model_dump_json()`` result.
        The file is flushed after every frame so partial recordings are valid.

        Example::

            with mock.record_to("session.jsonl") as source:
                async for frame in source.stream():
                    ...
        """
        return _RecordCtx(self, Path(path))

    # ── TelemetrySource ABC ───────────────────────────────────────────────────

    def stream(self) -> AsyncIterator[TelemetryFrame]:  # type: ignore[override]
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryFrame]:
        dt = 1.0 / self._rate_hz if self._rate_hz > 0 else 0.0
        frame_idx = 0
        next_anomaly = self._anomaly_every + self._rng.randint(-3, 3)
        prev_positions = [0.0] * self._num_joints

        while not self._closed:
            t = frame_idx * dt

            # ── Positions: amplitude × sin(freq × t + phase_j) + Gaussian noise
            positions = [
                _POSITION_AMPLITUDE * math.sin(_POSITION_FREQ * t + self._phases[j])
                + self._rng.gauss(0.0, _POSITION_NOISE_STD)
                for j in range(self._num_joints)
            ]

            # ── Velocities: backward finite difference
            if dt > 0.0:
                velocities = [
                    (positions[j] - prev_positions[j]) / dt for j in range(self._num_joints)
                ]
            else:
                velocities = [0.0] * self._num_joints

            # ── Torques: constant baseline + Gaussian noise
            torques = [
                _BASELINE_TORQUE + self._rng.gauss(0.0, _TORQUE_NOISE_STD)
                for _ in range(self._num_joints)
            ]

            # ── Anomaly injection
            anomaly_flags: list[str] = []
            if frame_idx == next_anomaly:
                spike_joint = self._rng.randint(0, self._num_joints - 1)
                torques[spike_joint] = _TORQUE_SPIKE_VALUE
                anomaly_flags.append("torque_spike")
                next_anomaly = frame_idx + self._anomaly_every + self._rng.randint(-3, 3)
                log.debug(
                    "mock.anomaly_injected",
                    frame_idx=frame_idx,
                    joint=spike_joint,
                    next_anomaly=next_anomaly,
                )

            frame = TelemetryFrame(
                timestamp=datetime.now(UTC),
                joint_positions=positions,
                joint_velocities=velocities,
                joint_torques=torques,
                end_effector_pose=_ee_pose(positions),
                anomaly_flags=anomaly_flags,
            )

            if self._record_fh is not None:
                self._record_fh.write(frame.model_dump_json() + "\n")
                self._record_fh.flush()

            prev_positions = positions
            frame_idx += 1
            yield frame

            if dt > 0.0:
                await anyio.sleep(dt)

    async def close(self) -> None:
        self._closed = True
        if self._record_fh is not None:
            self._record_fh.close()
            self._record_fh = None


# ── Internal helpers ──────────────────────────────────────────────────────────


class _RecordCtx:
    """Sync context manager that opens a JSONL file and attaches it to *source*."""

    def __init__(self, source: MockSource, path: Path) -> None:
        self._source = source
        self._path = path

    def __enter__(self) -> MockSource:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._source._record_fh = self._path.open("w", encoding="utf-8")
        return self._source

    def __exit__(self, *_: object) -> None:
        if self._source._record_fh is not None:
            self._source._record_fh.close()
            self._source._record_fh = None


def _ee_pose(positions: list[float]) -> dict[str, float]:
    """Simplified end-effector pose: treat first 3 joint positions as x/y/z proxy."""
    n = len(positions)
    return {
        "x": round(positions[0] if n > 0 else 0.0, 6),
        "y": round(positions[1] if n > 1 else 0.0, 6),
        "z": round(positions[2] if n > 2 else 0.5, 6),
    }


# ── ReplaySource ──────────────────────────────────────────────────────────────


class ReplaySource(TelemetrySource):
    """
    Replay a JSONL session recorded by ``MockSource.record_to()`` deterministically.

    Useful for:
    - Debugging a specific anomaly sequence without waiting for it to occur live.
    - CI tests that need a fixed, known frame sequence.
    - Demo rehearsal: replay a pre-recorded "perfect" session.

    The replayed frames are byte-identical to the originals: the same SHA-256 hashes
    produced at recording time will be reproduced on replay.
    """

    def __init__(self, path: Path | str, rate_hz: float = 10.0) -> None:
        self._path = Path(path)
        self._rate_hz = rate_hz

    def stream(self) -> AsyncIterator[TelemetryFrame]:  # type: ignore[override]
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryFrame]:
        dt = 1.0 / self._rate_hz if self._rate_hz > 0 else 0.0
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                frame = TelemetryFrame.model_validate_json(line)
                yield frame
                if dt > 0.0:
                    await anyio.sleep(dt)

    async def close(self) -> None:
        pass

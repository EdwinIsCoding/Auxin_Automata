"""TwinSource — TelemetrySource backed by a live PyBullet simulation.

This is the agnosticism-contract implementation for AUXIN_SOURCE=twin.
The bridge and all downstream consumers call only stream() and close() —
identical to MockSource and ROS2Source.

Simulation architecture
-----------------------
Each call to stream() creates a fresh RobotScene + PickAndPlace planner.
The simulation is driven synchronously inside the async generator at
*sim_steps_per_frame* steps per yielded TelemetryFrame, then the generator
sleeps for *1 / rate_hz* seconds before yielding the next frame.

Using rate_hz=0 in tests skips all sleeps, so 100 frames complete in
milliseconds without any wall-clock waiting.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import anyio
import structlog

from auxin_sdk.schema import TelemetryFrame
from auxin_sdk.sources.base import TelemetrySource

log = structlog.get_logger(__name__)


class TwinSource(TelemetrySource):
    """
    Live PyBullet telemetry source.

    Parameters
    ----------
    rate_hz
        Telemetry frames per second.  Use ``0`` in tests to skip sleeps.
    sim_rate_hz
        Internal simulation rate in Hz.  Determines physics fidelity.
        sim_steps_per_frame = round(sim_rate_hz / rate_hz) when rate_hz > 0.
    gui
        Launch PyBullet with GUI window.  Default: DIRECT (headless).
    force_collision_after
        If > 0, teleport the obstacle onto the EEF after this many frames.
        Set via TWIN_FORCE_COLLISION env var for the E2E anomaly demo.
    """

    def __init__(
        self,
        rate_hz: float = 10.0,
        sim_rate_hz: float = 240.0,
        gui: bool = False,
        force_collision_after: int = 0,
    ) -> None:
        import os

        self._rate_hz = rate_hz
        self._sim_rate_hz = sim_rate_hz
        self._gui = gui
        self._closed = False
        # TWIN_FORCE_COLLISION=N teleports the obstacle to the EEF after N frames.
        # This is the E2E anomaly trigger for demo / testing purposes.
        env_val = os.environ.get("TWIN_FORCE_COLLISION", "")
        self._force_collision_after: int = (
            int(env_val) if env_val.isdigit() else force_collision_after
        )

    # ── TelemetrySource ABC ───────────────────────────────────────────────────

    def stream(self) -> AsyncIterator[TelemetryFrame]:  # type: ignore[override]
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryFrame]:
        from .scene import RobotScene
        from .trajectory import PickAndPlace

        dt = 1.0 / self._rate_hz if self._rate_hz > 0 else 0.0

        # How many sim steps to run before yielding one telemetry frame.
        # With rate_hz=0 (test mode) we run 1 step per frame for determinism.
        if self._rate_hz > 0:
            sim_steps_per_frame = max(1, round(self._sim_rate_hz / self._rate_hz))
        else:
            sim_steps_per_frame = 1

        scene = RobotScene(gui=self._gui, sim_rate_hz=self._sim_rate_hz)
        trajectory = PickAndPlace()
        frame_count = 0

        log.debug(
            "twin_source.started",
            rate_hz=self._rate_hz,
            sim_rate_hz=self._sim_rate_hz,
            sim_steps_per_frame=sim_steps_per_frame,
            force_collision_after=self._force_collision_after,
        )

        try:
            while not self._closed:
                # ── Advance simulation
                for _ in range(sim_steps_per_frame):
                    trajectory.step(scene)

                frame_count += 1

                # ── Force collision for demo / E2E testing
                if self._force_collision_after > 0 and frame_count == self._force_collision_after:
                    log.info("twin_source.forcing_collision", frame=frame_count)
                    scene.teleport_obstacle_to_eef()

                # ── Read robot state
                positions, velocities, torques = scene.joint_states()
                eef = scene.eef_pose()

                # ── Collision detection — populates anomaly_flags
                anomaly_flags: list[str] = []
                if scene.has_collision():
                    anomaly_flags = ["collision_detected"]
                    log.warning("twin_source.collision_detected", frame=frame_count)

                frame = TelemetryFrame(
                    timestamp=datetime.now(timezone.utc),
                    joint_positions=positions,
                    joint_velocities=velocities,
                    joint_torques=torques,
                    end_effector_pose=eef,
                    anomaly_flags=anomaly_flags,
                )

                yield frame

                if dt > 0.0:
                    await anyio.sleep(dt)

        finally:
            scene.close()
            log.debug("twin_source.closed")

    async def close(self) -> None:
        """Signal the stream generator to stop on its next iteration."""
        self._closed = True

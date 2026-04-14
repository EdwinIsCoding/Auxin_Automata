"""Pre-scripted pick-and-place trajectory for the Franka Panda.

The trajectory cycles through a fixed sequence of end-effector waypoints.
At each simulation step the planner:
1. Solves IK for the current waypoint's target position.
2. Sends position-control targets to all arm joints.
3. Advances to the next waypoint after *_STEPS_PER_WAYPOINT* sim steps.

The loop repeats indefinitely so a TwinSource can stream frames without a
fixed end-of-sequence.

Waypoint sequence
-----------------
pre_grasp  →  grasp  →  lift  →  transport  →  place  →  retract  →  (repeat)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .scene import RobotScene

# ── Waypoint definitions ──────────────────────────────────────────────────────

# Each entry: (target_xyz, label)
_WAYPOINTS: list[tuple[list[float], str]] = [
    ([0.40,  0.00, 0.62], "pre_grasp"),   # above pick spot (robot base at z=0.70)
    ([0.40,  0.00, 0.42], "grasp"),        # lower to object height
    ([0.40,  0.00, 0.62], "lift"),         # lift back up
    ([0.40,  0.30, 0.62], "transport"),    # swing to place column
    ([0.40,  0.30, 0.42], "place"),        # lower to place height
    ([0.40,  0.30, 0.62], "retract"),      # retract upward
]

# Number of simulation steps to hold each waypoint before advancing.
# At 240 Hz sim rate this is ~0.25 s per waypoint (60 / 240 = 0.25 s).
_STEPS_PER_WAYPOINT: int = 60


class PickAndPlace:
    """
    Cyclic pick-and-place IK planner for RobotScene.

    Parameters
    ----------
    steps_per_waypoint
        How many simulation steps to dwell at each waypoint before advancing.
        Override in tests to shorten sequences.
    """

    def __init__(self, steps_per_waypoint: int = _STEPS_PER_WAYPOINT) -> None:
        self._steps_per_waypoint = steps_per_waypoint
        self._waypoint_idx: int = 0
        self._steps_at_waypoint: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def current_label(self) -> str:
        """Human-readable label of the active waypoint."""
        return _WAYPOINTS[self._waypoint_idx][1]

    @property
    def waypoint_idx(self) -> int:
        """Zero-based index into the waypoint list."""
        return self._waypoint_idx

    def step(self, scene: "RobotScene") -> str:
        """
        Advance one simulation step.

        Solves IK for the current waypoint, sends joint targets, steps the
        physics, and advances the waypoint counter when the dwell time expires.

        Returns
        -------
        str
            The label of the waypoint that was *active* during this step.
        """
        target_pos, label = _WAYPOINTS[self._waypoint_idx]
        joint_targets = scene.ik(target_pos)
        scene.set_joint_targets(joint_targets)
        scene.step()

        self._steps_at_waypoint += 1
        if self._steps_at_waypoint >= self._steps_per_waypoint:
            self._waypoint_idx = (self._waypoint_idx + 1) % len(_WAYPOINTS)
            self._steps_at_waypoint = 0

        return label

    def reset(self) -> None:
        """Restart from the first waypoint."""
        self._waypoint_idx = 0
        self._steps_at_waypoint = 0

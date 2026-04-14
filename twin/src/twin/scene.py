"""PyBullet scene: Franka Panda arm, flat table, and a red obstacle box.

The scene owns the physics server connection.  All PyBullet calls go through
the stored ``_client`` id so multiple scenes can coexist in the same process
(useful when pytest spawns several tests in parallel).

Design notes
------------
- DIRECT mode (headless) is used everywhere except interactive demos (``gui=True``).
- ``capture_frame()`` renders with ER_TINY_RENDERER so no OpenGL / display
  is required — CI-safe.
- The Franka Panda URDF ships with pybullet_data; no external asset downloads.
"""

from __future__ import annotations

import io

import numpy as np
import pybullet
import pybullet_data
from PIL import Image  # pillow — installed as a transitive dep of imageio

# ── Robot constants ───────────────────────────────────────────────────────────

NUM_ARM_JOINTS: int = 7  # joints 0-6 (panda_joint1 … panda_joint7)
EEF_LINK: int = 11  # panda_hand
_FINGER_JOINTS: list[int] = [9, 10]  # kept at 0 (closed)

# Franka Panda "ready" pose (radians) — visually neutral, away from singularities
_HOME_JOINTS: list[float] = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]

# Camera parameters for capture_frame()
_EYE: list[float] = [1.2, 0.8, 1.1]
_TARGET: list[float] = [0.4, 0.0, 0.6]
_UP: list[float] = [0.0, 0.0, 1.0]
_FOV: float = 55.0


class RobotScene:
    """
    Headless PyBullet scene with Franka Panda, table, and obstacle.

    Parameters
    ----------
    gui
        Launch with GUI (GUI mode).  Default: DIRECT (headless).
    sim_rate_hz
        Simulation timestep = 1 / sim_rate_hz.  Default: 240 Hz.
    """

    def __init__(self, gui: bool = False, sim_rate_hz: float = 240.0) -> None:
        self._sim_rate_hz = sim_rate_hz
        self._sim_dt = 1.0 / sim_rate_hz

        connection_mode = pybullet.GUI if gui else pybullet.DIRECT
        self._client: int = pybullet.connect(connection_mode)

        self._setup()

    # ── Private setup ─────────────────────────────────────────────────────────

    def _setup(self) -> None:
        p = pybullet
        c = self._client

        p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=c)
        p.setGravity(0.0, 0.0, -9.81, physicsClientId=c)
        p.setTimeStep(self._sim_dt, physicsClientId=c)

        # Ground plane
        p.loadURDF("plane.urdf", physicsClientId=c)

        # Table — positioned so its top surface is at z = 0.70 m
        half = [0.35, 0.55, 0.35]
        col = p.createCollisionShape(p.GEOM_BOX, halfExtents=half, physicsClientId=c)
        vis = p.createVisualShape(
            p.GEOM_BOX, halfExtents=half, rgbaColor=[0.76, 0.60, 0.42, 1.0], physicsClientId=c
        )
        p.createMultiBody(0, col, vis, [0.5, 0.0, 0.35], physicsClientId=c)

        # Robot base sits on the table top (z = 0.70)
        self._robot: int = p.loadURDF(
            "franka_panda/panda.urdf",
            basePosition=[0.0, 0.0, 0.70],
            useFixedBase=True,
            physicsClientId=c,
        )

        # Obstacle — red box on the table surface
        obs_half = [0.04, 0.04, 0.07]
        obs_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=obs_half, physicsClientId=c)
        obs_vis = p.createVisualShape(
            p.GEOM_BOX, halfExtents=obs_half, rgbaColor=[0.90, 0.10, 0.10, 0.90], physicsClientId=c
        )
        self._obstacle: int = p.createMultiBody(
            0, obs_col, obs_vis, [0.50, 0.18, 0.77], physicsClientId=c
        )

        # Reset arm to home pose; close fingers
        for i, angle in enumerate(_HOME_JOINTS):
            p.resetJointState(self._robot, i, angle, physicsClientId=c)
        for fi in _FINGER_JOINTS:
            p.resetJointState(self._robot, fi, 0.0, physicsClientId=c)

        # Warm up: let gravity settle the scene for a few steps
        for _ in range(10):
            p.stepSimulation(physicsClientId=c)

    # ── Simulation control ────────────────────────────────────────────────────

    def step(self) -> None:
        """Advance the simulation by one timestep (1 / sim_rate_hz seconds)."""
        pybullet.stepSimulation(physicsClientId=self._client)

    # ── Collision detection ───────────────────────────────────────────────────

    def has_collision(self) -> bool:
        """Return True if any robot link is currently in contact with the obstacle."""
        contacts = pybullet.getContactPoints(
            bodyA=self._robot,
            bodyB=self._obstacle,
            physicsClientId=self._client,
        )
        return len(contacts) > 0

    def teleport_obstacle_to_eef(self) -> None:
        """Move the obstacle directly to the end-effector position to force a collision."""
        eef = self.eef_pose()
        pybullet.resetBasePositionAndOrientation(
            self._obstacle,
            [eef["x"], eef["y"], eef["z"]],
            [0, 0, 0, 1],
            physicsClientId=self._client,
        )
        # One physics step so contacts are registered
        pybullet.stepSimulation(physicsClientId=self._client)

    # ── Joint state readout ───────────────────────────────────────────────────

    def joint_states(
        self,
    ) -> tuple[list[float], list[float], list[float]]:
        """
        Return (positions, velocities, torques) for the 7 arm joints.

        Torque is the *applied* motor torque (index 3 of getJointState output).
        """
        states = [
            pybullet.getJointState(self._robot, i, physicsClientId=self._client)
            for i in range(NUM_ARM_JOINTS)
        ]
        positions = [float(s[0]) for s in states]
        velocities = [float(s[1]) for s in states]
        torques = [float(s[3]) for s in states]
        return positions, velocities, torques

    def eef_pose(self) -> dict[str, float]:
        """Return end-effector world pose as {x, y, z, qx, qy, qz, qw}."""
        state = pybullet.getLinkState(self._robot, EEF_LINK, physicsClientId=self._client)
        pos: tuple[float, float, float] = state[0]
        orn: tuple[float, float, float, float] = state[1]
        return {
            "x": round(pos[0], 6),
            "y": round(pos[1], 6),
            "z": round(pos[2], 6),
            "qx": round(orn[0], 6),
            "qy": round(orn[1], 6),
            "qz": round(orn[2], 6),
            "qw": round(orn[3], 6),
        }

    # ── Actuation ─────────────────────────────────────────────────────────────

    def ik(self, target_pos: list[float]) -> list[float]:
        """
        Compute IK for target end-effector *position* (orientation unconstrained).

        Returns a list of 7 joint angles.
        """
        solution = pybullet.calculateInverseKinematics(
            self._robot,
            EEF_LINK,
            target_pos,
            physicsClientId=self._client,
        )
        return list(solution[:NUM_ARM_JOINTS])

    def set_joint_targets(self, positions: list[float]) -> None:
        """Drive each arm joint toward *positions* using position control."""
        for i, target in enumerate(positions[:NUM_ARM_JOINTS]):
            pybullet.setJointMotorControl2(
                self._robot,
                i,
                pybullet.POSITION_CONTROL,
                targetPosition=target,
                force=500.0,
                physicsClientId=self._client,
            )

    # ── Rendering ─────────────────────────────────────────────────────────────

    def capture_frame(self, width: int = 320, height: int = 240) -> bytes:
        """
        Render the current scene to JPEG bytes.

        Uses ER_TINY_RENDERER — works without a display or OpenGL context.
        """
        view = pybullet.computeViewMatrix(
            cameraEyePosition=_EYE,
            cameraTargetPosition=_TARGET,
            cameraUpVector=_UP,
        )
        proj = pybullet.computeProjectionMatrixFOV(
            fov=_FOV,
            aspect=float(width) / float(height),
            nearVal=0.1,
            farVal=10.0,
        )
        _, _, rgba, _, _ = pybullet.getCameraImage(
            width,
            height,
            view,
            proj,
            renderer=pybullet.ER_TINY_RENDERER,
            physicsClientId=self._client,
        )
        rgb = np.array(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3]
        return _encode_jpeg(rgb)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Disconnect from the PyBullet physics server."""
        try:
            pybullet.disconnect(self._client)
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────


def _encode_jpeg(rgb: np.ndarray, quality: int = 85) -> bytes:
    """Encode an (H, W, 3) uint8 numpy array as JPEG bytes via Pillow."""
    img = Image.fromarray(rgb, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()

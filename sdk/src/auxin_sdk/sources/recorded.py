"""RecordedSource — replay LeRobot-format Franka Emika Panda recordings.

Implements TelemetrySource so the bridge treats recorded data identically to
MockSource, TwinSource, and ROS2Source.  Selecting it requires only:

    AUXIN_SOURCE=recorded
    AUXIN_EPISODE_DIR=/path/to/episode_dir
    AUXIN_PLAYBACK_SPEED=1.0          # optional, default 1.0
    AUXIN_CAMERA_KEY=ee_zed_m_left    # optional, default ee_zed_m_left

Episode directory layout (LeRobot format):
    episode_dir/
      robot.jsonl                    # per-timestep joint state
      episode_events.jsonl           # episode-level events
      session_metadata.json          # fps, robot config
      cameras/
        ee_zed_m_left/
          rgb.mp4
          frames.jsonl               # per-frame {host_timestamp_ns, rgb_video_frame}
          metadata.json
        ee_zed_m_right/  ...
        third_person_d405/  ...

robot.jsonl row schema (relevant fields):
    {
      "robot_state": {
        "q":  [7 floats],     # joint positions, radians
        "dq": [7 floats],     # joint velocities, rad/s
        "tcp_position_xyz":     [x, y, z],
        "tcp_orientation_xyzw": [x, y, z, w],
        "gripper_state": "OPEN"|"CLOSED",
        "gripper_width": float
      },
      "status": {
        "fault_flags": {
          "control_exception": bool,
          "gripper_fault": bool,
          "ik_rejected": bool,
          "workspace_clamped": bool,
          ...
        }
      },
      "timestamp_ns": int
    }

frames.jsonl row schema:
    {
      "host_timestamp_ns": int,
      "rgb_video_frame":   int,   # 0-indexed frame in rgb.mp4
      "frame_index":       int,
      ...
    }
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import anyio

from ..schema import TelemetryFrame
from .base import TelemetrySource

log = logging.getLogger(__name__)

# Fault flags that map to anomaly strings
_FAULT_MAP: dict[str, str] = {
    "control_exception": "control_exception",
    "gripper_fault": "gripper_fault",
    "ik_rejected": "ik_rejected",
    "workspace_clamped": "workspace_clamped",
    "packet_timeout": "packet_timeout",
    "jump_rejected": "jump_rejected",
}

_DEFAULT_TORQUE_THRESHOLD = 30.0  # N·m — lower than watchdog (80) for early warning


class RecordedSource(TelemetrySource):
    """
    Replay a single LeRobot-format episode as a live telemetry stream.

    The bridge calls only source.stream() and source.close() — identical to
    MockSource and ROS2Source.  Bridge and all downstream code remain fully
    source-agnostic; only run_bridge.py branches on AUXIN_SOURCE=recorded.

    Extra methods (optional, called by bridge only via getattr duck-typing):
        get_frame_sync_info() → dict   for live video sync in dashboard
        get_video_path(camera_key)     for bridge video endpoint
    """

    def __init__(
        self,
        episode_dir: Path | str,
        *,
        playback_speed: float = 1.0,
        loop: bool = True,
        max_loops: int = 0,
        camera_key: str = "ee_zed_m_left",
        torque_threshold: float = _DEFAULT_TORQUE_THRESHOLD,
    ) -> None:
        self._episode_dir = Path(episode_dir)
        self._playback_speed = max(playback_speed, 0.01)
        self._loop = loop
        self._max_loops = max_loops  # 0 = unlimited
        self._camera_key = camera_key
        self._torque_threshold = torque_threshold

        # Loaded data
        self._robot_rows: list[dict[str, Any]] = []
        self._frame_map: list[dict[str, Any]] = []  # frames.jsonl entries sorted by timestamp
        self._camera_fps: float = 30.0

        # Video capture (lazy-opened on first get_frame_at call)
        self._cap: Any = None  # cv2.VideoCapture — imported lazily
        self._cap_camera_key: str | None = None
        # Lock protecting self._cap — get_frame_at is called from a threadpool
        # executor and can be invoked by multiple workers concurrently.
        self._cap_lock = threading.Lock()

        # Playback state (updated by stream, read by get_frame_sync_info)
        self._current_idx: int = 0
        self._loop_count: int = 0
        self._closed: bool = False

        self._load()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Parse robot.jsonl, session_metadata.json, and the camera frames.jsonl."""
        robot_path = self._episode_dir / "robot.jsonl"
        if not robot_path.exists():
            raise FileNotFoundError(f"robot.jsonl not found in {self._episode_dir}")

        with robot_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    self._robot_rows.append(json.loads(line))

        if not self._robot_rows:
            raise ValueError(f"robot.jsonl in {self._episode_dir} is empty")

        log.info("recorded_source.loaded robot.jsonl rows=%d", len(self._robot_rows))

        # Session metadata — extract camera FPS if available
        meta_path = self._episode_dir / "session_metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            zed_fps = (
                meta.get("config", {}).get("zed", {}).get("fps")
                or meta.get("config", {}).get("realsense", {}).get("fps")
            )
            if zed_fps:
                self._camera_fps = float(zed_fps)

        # Camera frames.jsonl — build timestamp → video frame index map
        frames_path = self._episode_dir / "cameras" / self._camera_key / "frames.jsonl"
        if frames_path.exists():
            with frames_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        self._frame_map.append(json.loads(line))
            # Sort by host_timestamp_ns for binary search
            self._frame_map.sort(key=lambda r: r.get("host_timestamp_ns", 0))
            log.info(
                "recorded_source.loaded frames.jsonl camera=%s entries=%d",
                self._camera_key,
                len(self._frame_map),
            )
        else:
            log.warning(
                "recorded_source.no_frames_jsonl camera=%s — get_frame_at will return None",
                self._camera_key,
            )

    # ── TelemetrySource interface ─────────────────────────────────────────────

    async def stream(self) -> AsyncIterator[TelemetryFrame]:  # type: ignore[override]
        """
        Yield TelemetryFrames at the original recording rate, adjusted by playback_speed.
        Emits replay_session_start / replay_session_end anomaly frames around each loop.
        When loop=True, restarts from frame 0 indefinitely.
        """
        while not self._closed:
            # ── Session start sentinel ────────────────────────────────────────
            yield self._make_session_sentinel("replay_session_start")

            # ── Main replay loop ──────────────────────────────────────────────
            start_ns = self._robot_rows[0].get("timestamp_ns", 0)

            for idx, row in enumerate(self._robot_rows):
                if self._closed:
                    return

                self._current_idx = idx
                frame = self._parse_row(row)
                yield frame

                # Sleep to match original timing, scaled by playback_speed.
                # Cap at 2 seconds to skip over idle gaps in the recording
                # (e.g. pauses between episodes, operator idle time).
                if idx < len(self._robot_rows) - 1:
                    next_ns = self._robot_rows[idx + 1].get("timestamp_ns", 0)
                    curr_ns = row.get("timestamp_ns", 0)
                    delta_s = min((next_ns - curr_ns) / 1e9, 2.0)
                    if delta_s > 0:
                        await anyio.sleep(delta_s / self._playback_speed)

            # ── Session end sentinel ──────────────────────────────────────────
            self._current_idx = len(self._robot_rows) - 1
            yield self._make_session_sentinel("replay_session_end")

            self._loop_count += 1
            log.info(
                "recorded_source.loop_complete loop=%d rows=%d",
                self._loop_count,
                len(self._robot_rows),
            )

            if not self._loop:
                break
            if self._max_loops > 0 and self._loop_count >= self._max_loops:
                log.info(
                    "recorded_source.max_loops_reached max=%d",
                    self._max_loops,
                )
                break

    async def close(self) -> None:
        """Release the video capture and stop the stream."""
        self._closed = True
        with self._cap_lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
        log.info("recorded_source.closed")

    # ── Optional methods (duck-typed by bridge) ───────────────────────────────

    def get_frame_sync_info(self) -> dict[str, Any]:
        """
        Return playback position info for dashboard video sync.
        Called by bridge every telemetry broadcast — never raises.
        """
        total = len(self._robot_rows)
        progress = self._current_idx / max(total - 1, 1)
        return {
            "frame_index": self._current_idx,
            "total_frames": total,
            "episode_progress": round(progress, 4),
            "camera_key": self._camera_key,
            "loop_count": self._loop_count,
        }

    def get_video_path(self, camera_key: str | None = None) -> Path | None:
        """
        Return the path to the MP4 for the specified camera.
        Falls back to the default camera_key if camera_key is None.
        Returns None if the file does not exist.
        """
        key = camera_key or self._camera_key
        path = self._episode_dir / "cameras" / key / "rgb.mp4"
        return path if path.exists() else None

    def get_frame_at(self, robot_frame_idx: int) -> Optional["np.ndarray"]:  # type: ignore[name-defined]
        """
        Return the RGB frame from the video file closest to the given robot frame index.
        Returns None if the video is unavailable or the index is out of range.

        Thread-safe: protected by _cap_lock since this is called from a threadpool
        executor and multiple workers (payment + scene) can invoke it concurrently.
        """
        if not self._frame_map or robot_frame_idx >= len(self._robot_rows):
            return None

        video_path = self.get_video_path()
        if video_path is None:
            return None

        with self._cap_lock:
            # Lazy-open video capture
            self._ensure_cap(video_path)
            if self._cap is None:
                return None

            # Find the corresponding video frame via the frame map
            # Match by relative position in the recording
            robot_progress = robot_frame_idx / max(len(self._robot_rows) - 1, 1)
            map_idx = min(
                int(robot_progress * len(self._frame_map)),
                len(self._frame_map) - 1,
            )
            video_frame_idx = self._frame_map[map_idx].get("rgb_video_frame", map_idx)

            try:
                self._cap.set(1, video_frame_idx)  # CAP_PROP_POS_FRAMES = 1
                ret, frame = self._cap.read()
                if ret and frame is not None:
                    import cv2
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except Exception as exc:
                log.warning("recorded_source.frame_read_error error=%s", exc)

        return None

    def get_available_cameras(self) -> list[str]:
        """Return a list of camera keys with a valid rgb.mp4."""
        cameras_dir = self._episode_dir / "cameras"
        if not cameras_dir.exists():
            return []
        return [
            d.name
            for d in sorted(cameras_dir.iterdir())
            if d.is_dir() and (d / "rgb.mp4").exists()
        ]

    @property
    def total_frames(self) -> int:
        return len(self._robot_rows)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parse_row(self, row: dict[str, Any]) -> TelemetryFrame:
        """Convert one robot.jsonl row to a TelemetryFrame."""
        rs = row.get("robot_state", {})
        status = row.get("status", {})

        q: list[float] = rs.get("q", []) or [0.0] * 7
        dq: list[float] = rs.get("dq", []) or [0.0] * 7
        # Torques are not recorded in this dataset; use zeros
        torques: list[float] = [0.0] * len(q)

        # End-effector pose from TCP fields
        pos: list[float] = rs.get("tcp_position_xyz", [0.0, 0.0, 0.0])
        quat: list[float] = rs.get("tcp_orientation_xyzw", [0.0, 0.0, 0.0, 1.0])
        end_effector_pose: dict[str, Any] = {
            "x": pos[0] if len(pos) > 0 else 0.0,
            "y": pos[1] if len(pos) > 1 else 0.0,
            "z": pos[2] if len(pos) > 2 else 0.0,
            "qx": quat[0] if len(quat) > 0 else 0.0,
            "qy": quat[1] if len(quat) > 1 else 0.0,
            "qz": quat[2] if len(quat) > 2 else 0.0,
            "qw": quat[3] if len(quat) > 3 else 1.0,
            "gripper_state": rs.get("gripper_state", "UNKNOWN"),
            "gripper_width": rs.get("gripper_width", 0.0),
        }

        # Anomaly detection from fault flags
        anomaly_flags: list[str] = []
        fault_flags: dict[str, bool] = status.get("fault_flags", {})
        for flag_key, anomaly_str in _FAULT_MAP.items():
            if fault_flags.get(flag_key):
                anomaly_flags.append(anomaly_str)

        # Torque spike check (if torques were available)
        if torques and max(abs(t) for t in torques) > self._torque_threshold:
            anomaly_flags.append("torque_spike")

        return TelemetryFrame(
            timestamp=datetime.now(timezone.utc),
            joint_positions=q[:7] if len(q) >= 7 else q + [0.0] * (7 - len(q)),
            joint_velocities=dq[:7] if len(dq) >= 7 else dq + [0.0] * (7 - len(dq)),
            joint_torques=torques[:7] if len(torques) >= 7 else torques + [0.0] * (7 - len(torques)),
            end_effector_pose=end_effector_pose,
            anomaly_flags=anomaly_flags,
        )

    def _make_session_sentinel(self, flag: str) -> TelemetryFrame:
        """Emit a minimal TelemetryFrame marking the start or end of a replay session."""
        # Use the first or last frame's joint state as context
        row = self._robot_rows[0] if flag.endswith("start") else self._robot_rows[-1]
        rs = row.get("robot_state", {})
        q = rs.get("q", [0.0] * 7)
        dq = rs.get("dq", [0.0] * 7)
        n = max(len(q), 7)
        return TelemetryFrame(
            timestamp=datetime.now(timezone.utc),
            joint_positions=(q + [0.0] * n)[:7],
            joint_velocities=(dq + [0.0] * n)[:7],
            joint_torques=[0.0] * 7,
            end_effector_pose={"x": 0.0, "y": 0.0, "z": 0.0, "qw": 1.0},
            anomaly_flags=[flag],
        )

    def _ensure_cap(self, video_path: Path) -> None:
        """Lazy-open the video capture if it's not already open for this path."""
        if self._cap is not None and self._cap_camera_key == self._camera_key:
            return
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        try:
            import cv2
            self._cap = cv2.VideoCapture(str(video_path))
            if not self._cap.isOpened():
                log.warning("recorded_source.video_open_failed path=%s", video_path)
                self._cap = None
            else:
                # Disable FFmpeg's internal frame-level threading.
                # Random seeks (cap.set CAP_PROP_POS_FRAMES) trigger a race in
                # libavcodec's pthread_frame.c async_lock when multi-threading is
                # active, causing "Assertion fctx->async_lock failed" crashes.
                # CAP_PROP_THREAD_COUNT is not present in all OpenCV builds.
                _thread_prop = getattr(cv2, "CAP_PROP_THREAD_COUNT", None)
                if _thread_prop is not None:
                    self._cap.set(_thread_prop, 1)
                self._cap_camera_key = self._camera_key
                log.info("recorded_source.video_opened path=%s", video_path)
        except ImportError:
            log.warning("recorded_source.cv2_not_available — install opencv-python for frame extraction")
            self._cap = None
        except Exception as exc:
            log.warning("recorded_source.video_error error=%s", exc)
            self._cap = None

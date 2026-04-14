"""ROS2Source — TelemetrySource backed by live /joint_states from a physical arm.

This is the agnosticism-contract implementation for AUXIN_SOURCE=ros2.
The bridge calls only stream() and close() — identical to MockSource and TwinSource.

Threading model
---------------
rclpy requires its own spin loop.  ROS2Source starts rclpy in a daemon thread
and bridges frames into an asyncio.Queue using loop.call_soon_threadsafe().
The async generator in stream() yields from that queue on the bridge's event loop.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator

import structlog

from auxin_sdk.schema import TelemetryFrame
from auxin_sdk.sources.base import TelemetrySource

log = structlog.get_logger(__name__)


class ROS2Source(TelemetrySource):
    """
    Live ROS2 telemetry source for physical robot arms.

    Internally spins a ``TelemetryBridgeNode`` in a background thread.
    The node subscribes to ``/joint_states``, throttles to 2 Hz, converts
    each sample to a ``TelemetryFrame``, and pushes it into an asyncio queue
    that ``stream()`` yields from.

    Parameters
    ----------
    queue_maxsize
        Max frames buffered between the ROS2 thread and the async generator.
        If the bridge falls behind, oldest frames are dropped (the node
        always pushes the latest).
    """

    def __init__(self, queue_maxsize: int = 16) -> None:
        self._queue_maxsize = queue_maxsize
        self._queue: asyncio.Queue[TelemetryFrame | None] | None = None
        self._closed = False
        self._spin_thread: threading.Thread | None = None
        self._node: object | None = None  # typed as object to avoid top-level rclpy import

    # ── TelemetrySource ABC ───────────────────────────────────────────────────

    def stream(self) -> AsyncIterator[TelemetryFrame]:  # type: ignore[override]
        return self._stream()

    async def _stream(self) -> AsyncIterator[TelemetryFrame]:
        import rclpy

        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._queue_maxsize)

        # ── Initialise rclpy + node ──────────────────────────────────────────
        rclpy.init()

        from .telemetry_bridge_node import TelemetryBridgeNode

        topic = os.environ.get("JOINT_STATES_TOPIC", "/joint_states")
        rate_hz = float(os.environ.get("TELEMETRY_RATE_HZ", "2"))
        stale_timeout = float(os.environ.get("STALE_TIMEOUT_S", "1.0"))

        node = TelemetryBridgeNode(
            topic=topic,
            rate_hz=rate_hz,
            stale_timeout_s=stale_timeout,
            frame_callback=lambda frame: self._enqueue(frame, loop),
        )
        self._node = node

        # ── Spin rclpy in a daemon thread ────────────────────────────────────
        def _spin() -> None:
            try:
                rclpy.spin(node)
            except Exception:
                log.exception("ros2_source.spin_error")
            finally:
                node.destroy_node()
                rclpy.try_shutdown()

        self._spin_thread = threading.Thread(target=_spin, daemon=True, name="rclpy-spin")
        self._spin_thread.start()
        log.info(
            "ros2_source.started",
            topic=topic,
            rate_hz=rate_hz,
            stale_timeout_s=stale_timeout,
        )

        # ── Yield frames from the queue ──────────────────────────────────────
        try:
            while not self._closed:
                frame = await self._queue.get()
                if frame is None:
                    break
                yield frame
        finally:
            log.info("ros2_source.stream_ended")

    async def close(self) -> None:
        """Shut down the ROS2 node and spin thread.  Idempotent."""
        if self._closed:
            return
        self._closed = True

        # Unblock the queue consumer.
        if self._queue is not None:
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

        # Shut down rclpy — this causes rclpy.spin() to return.
        try:
            import rclpy

            rclpy.try_shutdown()
        except Exception:
            pass

        if self._spin_thread is not None:
            self._spin_thread.join(timeout=5.0)

        log.info("ros2_source.closed")

    # ── Internal ─────────────────────────────────────────────────────────────

    def _enqueue(self, frame: TelemetryFrame, loop: asyncio.AbstractEventLoop) -> None:
        """Thread-safe push from the rclpy thread into the asyncio queue."""
        try:
            loop.call_soon_threadsafe(self._queue_put_nowait, frame)
        except RuntimeError:
            # Event loop closed during shutdown — safe to ignore.
            pass

    def _queue_put_nowait(self, frame: TelemetryFrame) -> None:
        """Called on the event loop thread.  Drops oldest if full."""
        if self._queue is None:
            return
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            log.debug("ros2_source.frame_dropped", reason="queue_full")
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            pass

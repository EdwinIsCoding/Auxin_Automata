"""TelemetrySource ABC — the hardware-agnosticism contract.

This is the single most important file in the SDK for demonstrating
hardware-agnosticism to Colosseum judges.

Architecture rule
-----------------
ALL concrete sources must implement this interface exactly.  The bridge and
every downstream consumer call only ``source.stream()`` and ``source.close()``.
No code outside this file may branch on which source is active.  The source is
selected exclusively via the ``AUXIN_SOURCE`` environment variable.

Correct concrete implementation pattern
---------------------------------------
::

    class MockSource(TelemetrySource):
        async def stream(self) -> AsyncIterator[TelemetryFrame]:
            while True:
                yield await self._build_next_frame()

        async def close(self) -> None:
            pass  # no resources to release

Bridge usage
------------
::

    async for frame in source.stream():
        await bridge.process(frame)

Changing ``AUXIN_SOURCE`` from ``mock`` to ``twin`` to ``ros2`` is the ONLY
change required to switch between a synthetic generator, a PyBullet simulation,
and a physical robot arm.  This must show up as a one-line diff.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..schema import TelemetryFrame


class TelemetrySource(ABC):
    """
    Abstract base class for kinematic telemetry sources.

    Implementations
    ---------------
    ``MockSource``  (Phase 1B) — synthetic sine/cosine kinematics, no hardware
    ``TwinSource``  (Phase 1C) — PyBullet simulation, ``/twin`` workspace
    ``ROS2Source``  (Phase 2B) — live ``/joint_states`` from ROS2 on Jetson Orin Nano
    """

    @abstractmethod
    def stream(self) -> AsyncIterator[TelemetryFrame]:
        """
        Return an async iterator that yields ``TelemetryFrame`` objects indefinitely.

        Concrete implementations MUST be declared as ``async def stream(self)``
        with ``yield`` inside — i.e. they are async generator methods.  Async
        generators return the generator object immediately when called (no
        ``await`` needed), so the bridge iterates as::

            async for frame in source.stream():
                ...

        Do NOT return a coroutine here (i.e., no ``return`` of an awaitable).
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Release any resources held by this source.

        Called by the bridge on shutdown.  Must be idempotent.
        """
        ...

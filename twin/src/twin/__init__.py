"""auxin-twin — PyBullet digital twin and TwinSource for Auxin Automata.

Exposes TwinSource as the top-level public API; scene, trajectory, and render
are available as sub-modules for advanced use.
"""

from .source import TwinSource

__all__ = ["TwinSource"]

# auxin-twin — scaffolded in Phase 0.
# Modules are implemented in Phase 1C:
#   scene.py      — PyBullet scene loader (Franka Panda URDF, table, obstacle)
#   trajectory.py — pre-scripted IK pick-and-place loop
#   source.py     — TwinSource(TelemetrySource) conforming to the SDK ABC
#   render.py     — off-screen MP4 renderer + websocket frame server
#   __main__.py   — CLI entrypoint: python -m twin --mode [video|ws|both]

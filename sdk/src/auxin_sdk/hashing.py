"""Deterministic SHA-256 hashing of TelemetryFrame objects.

Design
------
Canonical JSON is produced with:
- ``sort_keys=True`` — field order is irrelevant to the hash
- ``separators=(',', ':')`` — no extraneous whitespace
- ``allow_nan=False`` — reject NaN/Infinity which are not valid JSON
- Floats serialised via Pydantic's ``model_dump(mode="json")`` which uses
  Python's ``float.__repr__``.  This is bit-exact and deterministic on
  CPython 3.11+ across all platforms.
- Datetime fields are ISO 8601 strings (via Pydantic's JSON encoder).

The resulting hash is the compliance log entry that gets written on-chain.
"""

from __future__ import annotations

import hashlib
import json

from .schema import TelemetryFrame


def canonical_json(frame: TelemetryFrame) -> str:
    """
    Serialise *frame* to a deterministic canonical JSON string.

    The output is stable: the same TelemetryFrame will always produce
    byte-identical output on CPython 3.11+, regardless of dict insertion order.
    """
    data = frame.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(frame: TelemetryFrame) -> str:
    """Return the lowercase hex-encoded SHA-256 digest of *frame*'s canonical JSON."""
    return hashlib.sha256(canonical_json(frame).encode("utf-8")).hexdigest()

"""Tests for auxin_sdk.hashing — canonical JSON and SHA-256 determinism."""

from __future__ import annotations

import json

from auxin_sdk.hashing import canonical_json, sha256_hex
from auxin_sdk.schema import TelemetryFrame

# ── canonical_json ────────────────────────────────────────────────────────────


def test_canonical_json_returns_string(canonical_frame: TelemetryFrame) -> None:
    result = canonical_json(canonical_frame)
    assert isinstance(result, str)
    assert len(result) > 0


def test_canonical_json_is_valid_json(canonical_frame: TelemetryFrame) -> None:
    """Output must be parseable JSON."""
    result = canonical_json(canonical_frame)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


def test_canonical_json_top_level_keys_are_sorted(canonical_frame: TelemetryFrame) -> None:
    """Top-level keys must appear in lexicographic order."""
    data = json.loads(canonical_json(canonical_frame))
    keys = list(data.keys())
    assert keys == sorted(keys), f"keys out of order: {keys}"


def test_canonical_json_nested_keys_are_sorted(canonical_frame: TelemetryFrame) -> None:
    """Nested dict keys (end_effector_pose) must also be sorted."""
    data = json.loads(canonical_json(canonical_frame))
    nested_keys = list(data["end_effector_pose"].keys())
    assert nested_keys == sorted(nested_keys)


def test_canonical_json_has_no_extra_whitespace(canonical_frame: TelemetryFrame) -> None:
    """Canonical JSON must use compact separators — no spaces after : or ,"""
    result = canonical_json(canonical_frame)
    assert ": " not in result, "no space after colon"
    assert ", " not in result, "no space after comma"


def test_canonical_json_same_frame_same_output(canonical_frame: TelemetryFrame) -> None:
    """Two calls on the same frame must produce byte-identical output."""
    assert canonical_json(canonical_frame) == canonical_json(canonical_frame)


def test_canonical_json_round_trip_stable(canonical_frame: TelemetryFrame) -> None:
    """Re-parsing canonical JSON and re-serialising must give the same string."""
    first = canonical_json(canonical_frame)
    restored = TelemetryFrame.model_validate(json.loads(first))
    second = canonical_json(restored)
    assert first == second, "canonical JSON must survive a parse-validate-serialise round-trip"


# ── sha256_hex ────────────────────────────────────────────────────────────────

# Canonical hash of the fixture frame — computed on CPython 3.11 and pinned here
# so any serialisation regression is caught immediately.
# canonical JSON: {"anomaly_flags":[],"end_effector_pose":{"pitch":0.0,"roll":0.0,
#   "x":0.5,"y":0.0,"yaw":0.0,"z":0.3},"joint_positions":[0.1,0.2,0.3,0.4,0.5,0.6],
#   "joint_torques":[1.0,2.0,3.0,4.0,5.0,6.0],"joint_velocities":[0.01,...],
#   "timestamp":"2024-01-01T00:00:00+00:00"}
CANONICAL_FRAME_SHA256 = "d8b59191fcbbb383e0bab8428f765b5f90c0682849c71d4ea0d869ca9f56f509"


def test_sha256_hex_is_64_lowercase_hex_chars(canonical_frame: TelemetryFrame) -> None:
    h = sha256_hex(canonical_frame)
    assert len(h) == 64
    assert h == h.lower()
    assert all(c in "0123456789abcdef" for c in h)


def test_sha256_hex_matches_pinned_value(canonical_frame: TelemetryFrame) -> None:
    """
    Regression guard: the canonical frame must produce this exact digest on CPython 3.11+.

    If this test fails, the serialisation format changed — update the hash only after
    confirming the change is intentional and re-auditing all on-chain compliance logs.
    """
    assert sha256_hex(canonical_frame) == CANONICAL_FRAME_SHA256


def test_sha256_hex_determinism_same_call(canonical_frame: TelemetryFrame) -> None:
    """Calling sha256_hex twice on the same object produces the same digest."""
    assert sha256_hex(canonical_frame) == sha256_hex(canonical_frame)


def test_sha256_hex_determinism_after_round_trip(canonical_frame: TelemetryFrame) -> None:
    """
    A frame reconstructed from its own canonical JSON must hash identically.

    This is the critical guarantee: the on-chain hash written by the bridge
    can be independently verified by anyone who re-serialises the frame.
    """
    h1 = sha256_hex(canonical_frame)
    reconstructed = TelemetryFrame.model_validate(json.loads(canonical_json(canonical_frame)))
    h2 = sha256_hex(reconstructed)
    assert h1 == h2, "hash must survive a canonical-JSON round-trip"


def test_sha256_hex_differs_for_different_frames(
    canonical_frame: TelemetryFrame,
    anomalous_frame: TelemetryFrame,
) -> None:
    """Frames with different content must produce different digests."""
    assert sha256_hex(canonical_frame) != sha256_hex(anomalous_frame)


def test_sha256_hex_sensitive_to_single_field_change(canonical_frame: TelemetryFrame) -> None:
    """Modifying a single field by any amount must change the digest."""
    original = sha256_hex(canonical_frame)

    data = canonical_frame.model_dump()
    data["joint_torques"][2] = 99.9
    modified = TelemetryFrame(**data)

    assert sha256_hex(modified) != original


def test_sha256_hex_sensitive_to_anomaly_flag(canonical_frame: TelemetryFrame) -> None:
    """Adding an anomaly flag must change the digest."""
    original = sha256_hex(canonical_frame)

    data = canonical_frame.model_dump()
    data["anomaly_flags"] = ["torque_spike"]
    flagged = TelemetryFrame(**data)

    assert sha256_hex(flagged) != original

"""Nightly eval harness for SafetyOracle — requires GEMINI_API_KEY.

Runs the oracle against all 20 fixture images with synthetic safe and unsafe
telemetry, then asserts ≥ 90% accuracy.

CI runs this nightly in a dedicated job (not in the standard PR suite because
it costs API credits).

Usage
-----
    # Run manually (requires a real API key):
    GEMINI_API_KEY=<key> uv run pytest tests/eval_oracle.py -m network -v

    # CI nightly job runs via:
    uv run pytest tests/eval_oracle.py -m network --run-network -v
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from auxin_sdk.fixtures import all_fixture_images
from auxin_sdk.oracle import OracleDecision, SafetyOracle
from auxin_sdk.schema import TelemetryFrame

# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _safe_frame() -> TelemetryFrame:
    """Nominal telemetry — all torques well below the 80 N·m threshold."""
    return TelemetryFrame(
        timestamp=datetime.now(UTC),
        joint_positions=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        joint_velocities=[0.01] * 6,
        joint_torques=[5.0, 6.0, 7.0, 5.5, 4.8, 6.2],
        end_effector_pose={"x": 0.40, "y": 0.00, "z": 0.55},
        anomaly_flags=[],
    )


def _unsafe_frame_high_torque() -> TelemetryFrame:
    """Telemetry with a torque spike — should be denied regardless of image."""
    return TelemetryFrame(
        timestamp=datetime.now(UTC),
        joint_positions=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        joint_velocities=[0.01] * 6,
        joint_torques=[95.0, 6.0, 7.0, 5.5, 4.8, 6.2],  # joint 0 spiked
        end_effector_pose={"x": 0.40, "y": 0.00, "z": 0.55},
        anomaly_flags=["torque_spike"],
    )


# ── Image-based accuracy (safe telemetry) ─────────────────────────────────────


@pytest.mark.network
async def test_oracle_image_accuracy_90pct() -> None:
    """
    Oracle must correctly classify ≥ 90 % of the 20 fixture images
    when telemetry is nominal (decision driven by image content alone).

    Expected oracle behaviour:
    - clear_*.jpg  → action_approved = True
    - obstacle_*.jpg → action_approved = False
    """
    oracle = SafetyOracle()  # reads GEMINI_API_KEY from env
    fixtures = all_fixture_images()
    assert len(fixtures) == 20, f"expected 20 fixtures, got {len(fixtures)}"

    results: list[dict] = []

    for image_path, label in fixtures:
        frame = _safe_frame()
        expected = label == "clear"  # True → approve, False → deny

        decision = await oracle.check(frame, image_path)

        correct = decision.action_approved == expected
        results.append(
            {
                "image": image_path.name,
                "label": label,
                "expected": expected,
                "got": decision.action_approved,
                "correct": correct,
                "confidence": decision.confidence,
                "used_fallback": decision.used_fallback,
                "reason": decision.reason,
            }
        )

    correct_count = sum(r["correct"] for r in results)
    accuracy = correct_count / len(results)

    # Print per-image results for debugging CI failures
    print(f"\n{'Image':<22} {'Label':<9} {'Expected':<10} {'Got':<7} {'OK'}")
    print("-" * 60)
    for r in results:
        mark = "✓" if r["correct"] else "✗"
        print(
            f"{r['image']:<22} {r['label']:<9} {str(r['expected']):<10} {str(r['got']):<7} {mark}"
        )
    print(f"\nAccuracy: {correct_count}/{len(results)} = {accuracy:.1%}")

    assert accuracy >= 0.90, (
        f"Oracle accuracy {accuracy:.1%} is below the 90% threshold.\n"
        f"Failures:\n"
        + "\n".join(
            f"  {r['image']}: expected {r['expected']}, got {r['got']} (reason: {r['reason']})"
            for r in results
            if not r["correct"]
        )
    )


# ── High-torque deny (telemetry-driven) ───────────────────────────────────────


@pytest.mark.network
async def test_oracle_denies_all_high_torque_frames() -> None:
    """
    All 20 fixture images must be denied when telemetry has a torque spike.

    The torque threshold (80 N·m) is violated regardless of the image content,
    so the oracle must deny every one of these — even the 'clear' images.
    """
    oracle = SafetyOracle()
    fixtures = all_fixture_images()

    denial_count = 0
    for image_path, _label in fixtures:
        frame = _unsafe_frame_high_torque()
        decision = await oracle.check(frame, image_path)
        if not decision.action_approved:
            denial_count += 1

    assert denial_count == len(fixtures), (
        f"expected all {len(fixtures)} high-torque frames to be denied, "
        f"but only {denial_count} were denied"
    )


# ── No-stall guarantee ────────────────────────────────────────────────────────


@pytest.mark.network
async def test_oracle_completes_within_deadline() -> None:
    """
    Each oracle call must return within 5 seconds (network round-trip
    budget for Gemini + one retry).  The 2 s per-call timeout means a
    single retry can still fit within 5 s.
    """
    import time

    oracle = SafetyOracle(timeout_s=2.0)
    fixtures = all_fixture_images()[:5]  # sample 5 images to keep test fast

    for image_path, _label in fixtures:
        start = time.perf_counter()
        decision = await oracle.check(_safe_frame(), image_path)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"{image_path.name}: call took {elapsed:.2f}s — exceeded 5s budget"
        assert isinstance(decision, OracleDecision)

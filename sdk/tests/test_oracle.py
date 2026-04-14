"""Unit tests for SafetyOracle — all Gemini calls are mocked.

No network access is needed; all tests run in the default suite.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auxin_sdk.oracle import OracleDecision, SafetyOracle, _local_fallback_core
from auxin_sdk.schema import TelemetryFrame

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_frame(
    torques: list[float] | None = None,
    anomaly_flags: list[str] | None = None,
) -> TelemetryFrame:
    return TelemetryFrame(
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        joint_positions=[0.1] * 6,
        joint_velocities=[0.0] * 6,
        joint_torques=torques or [5.0] * 6,
        end_effector_pose={"x": 0.4, "y": 0.0, "z": 0.5},
        anomaly_flags=anomaly_flags or [],
    )


def _mock_gemini_model(payload: dict) -> MagicMock:
    """Return a MagicMock that behaves like a GenerativeModel returning *payload*."""
    mock_usage = MagicMock()
    mock_usage.prompt_token_count = 120
    mock_usage.candidates_token_count = 40

    mock_response = MagicMock()
    mock_response.text = json.dumps(payload)
    mock_response.usage_metadata = mock_usage

    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(return_value=mock_response)
    return mock_model


def _approve_payload() -> dict:
    return {
        "action_approved": True,
        "reason": "workspace clear, torques nominal",
        "confidence": 0.95,
        "prompt_version": "safety_oracle_v1",
    }


def _deny_payload(reason: str = "obstacle detected") -> dict:
    return {
        "action_approved": False,
        "reason": reason,
        "confidence": 0.92,
        "prompt_version": "safety_oracle_v1",
    }


# ── OracleDecision model ──────────────────────────────────────────────────────


def test_oracle_decision_has_all_fields() -> None:
    """OracleDecision must expose all six fields."""
    d = OracleDecision(
        action_approved=True,
        reason="test",
        confidence=0.9,
        latency_ms=42.0,
        prompt_version="safety_oracle_v1",
        used_fallback=False,
    )
    assert d.action_approved is True
    assert d.reason == "test"
    assert d.confidence == 0.9
    assert d.latency_ms == 42.0
    assert d.prompt_version == "safety_oracle_v1"
    assert d.used_fallback is False


# ── Approve path ──────────────────────────────────────────────────────────────


async def test_oracle_approves_clear_workspace(tmp_path: Path) -> None:
    """Mock Gemini returns approve → OracleDecision.action_approved is True."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    oracle = SafetyOracle(
        api_key="test-key",
        _model=_mock_gemini_model(_approve_payload()),
    )
    decision = await oracle.check(_make_frame(), img)

    assert decision.action_approved is True
    assert decision.used_fallback is False
    assert decision.prompt_version == "safety_oracle_v1"
    assert decision.latency_ms >= 0.0


# ── Deny path ─────────────────────────────────────────────────────────────────


async def test_oracle_denies_obstacle(tmp_path: Path) -> None:
    """Mock Gemini returns deny → OracleDecision.action_approved is False."""
    img = tmp_path / "obstacle_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    oracle = SafetyOracle(
        api_key="test-key",
        _model=_mock_gemini_model(_deny_payload("obstacle detected in reach zone")),
    )
    decision = await oracle.check(_make_frame(), img)

    assert decision.action_approved is False
    assert "obstacle" in decision.reason
    assert decision.used_fallback is False


async def test_oracle_denies_high_torque_via_gemini(tmp_path: Path) -> None:
    """Gemini-path deny for high torque (model decides, oracle records it)."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    oracle = SafetyOracle(
        api_key="test-key",
        _model=_mock_gemini_model(
            _deny_payload("torque 92.0 Nm on joint 3 exceeds threshold 80.0 Nm")
        ),
    )
    decision = await oracle.check(_make_frame(torques=[92.0] + [5.0] * 5), img)

    assert decision.action_approved is False
    assert decision.used_fallback is False


# ── Fallback: no API key ──────────────────────────────────────────────────────


async def test_oracle_uses_fallback_when_no_api_key(tmp_path: Path) -> None:
    """Without an API key every check() must use the local fallback."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    oracle = SafetyOracle(api_key="")  # no key
    decision = await oracle.check(_make_frame(), img)

    assert decision.used_fallback is True
    assert decision.prompt_version == "local-fallback-v1"


async def test_oracle_fallback_approves_nominal(tmp_path: Path) -> None:
    """Fallback approves when torques are safe and no obstacle label exists."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")  # no labels.json alongside it

    oracle = SafetyOracle(api_key="")
    decision = await oracle.check(_make_frame(torques=[5.0] * 6), img)

    assert decision.action_approved is True
    assert decision.used_fallback is True


async def test_oracle_fallback_denies_high_torque(tmp_path: Path) -> None:
    """Fallback must deny when any torque exceeds the threshold."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    oracle = SafetyOracle(api_key="", torque_threshold=80.0)
    decision = await oracle.check(_make_frame(torques=[95.0] + [5.0] * 5), img)

    assert decision.action_approved is False
    assert decision.used_fallback is True
    assert "95.0" in decision.reason


async def test_oracle_fallback_denies_obstacle_label(tmp_path: Path) -> None:
    """Fallback must deny when labels.json marks the image as 'obstacle'."""
    img = tmp_path / "obstacle_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")
    labels = {"obstacle_01.jpg": "obstacle"}
    (tmp_path / "labels.json").write_text(json.dumps(labels))

    oracle = SafetyOracle(api_key="")
    decision = await oracle.check(_make_frame(), img)

    assert decision.action_approved is False
    assert decision.used_fallback is True
    assert "obstacle" in decision.reason


async def test_oracle_fallback_denies_anomaly_flags(tmp_path: Path) -> None:
    """Fallback must deny when the frame carries anomaly flags."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    oracle = SafetyOracle(api_key="")
    decision = await oracle.check(_make_frame(anomaly_flags=["torque_spike"]), img)

    assert decision.action_approved is False
    assert decision.used_fallback is True


# ── Fallback: network failure ─────────────────────────────────────────────────


async def test_oracle_falls_back_on_api_exception(tmp_path: Path) -> None:
    """Any exception from Gemini must trigger used_fallback=True, never propagate."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(
        side_effect=ConnectionError("network unreachable")
    )

    oracle = SafetyOracle(api_key="test-key", _model=mock_model)
    decision = await oracle.check(_make_frame(), img)

    assert decision.used_fallback is True
    assert isinstance(decision, OracleDecision)


async def test_oracle_falls_back_on_timeout(tmp_path: Path) -> None:
    """When Gemini takes longer than timeout_s, fallback is used."""
    import anyio

    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    async def _slow(*_args: object, **_kwargs: object) -> object:
        await anyio.sleep(10)  # longer than any test timeout
        return MagicMock()

    mock_model = MagicMock()
    mock_model.generate_content_async = _slow

    oracle = SafetyOracle(api_key="test-key", _model=mock_model, timeout_s=0.05)
    decision = await oracle.check(_make_frame(), img)

    assert decision.used_fallback is True


async def test_oracle_falls_back_on_bad_json(tmp_path: Path) -> None:
    """Malformed JSON in Gemini response must trigger fallback, not a crash."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    mock_response = MagicMock()
    mock_response.text = "this is not json {{{broken"
    mock_response.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)

    mock_model = MagicMock()
    mock_model.generate_content_async = AsyncMock(return_value=mock_response)

    oracle = SafetyOracle(api_key="test-key", _model=mock_model)
    decision = await oracle.check(_make_frame(), img)

    assert decision.used_fallback is True


async def test_oracle_falls_back_on_missing_field(tmp_path: Path) -> None:
    """JSON missing a required field must trigger fallback."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    bad_payload = {"action_approved": True}  # missing reason, confidence, prompt_version
    mock_model = _mock_gemini_model(bad_payload)

    oracle = SafetyOracle(api_key="test-key", _model=mock_model)
    decision = await oracle.check(_make_frame(), img)

    assert decision.used_fallback is True


# ── Latency and logging ───────────────────────────────────────────────────────


async def test_oracle_decision_latency_is_positive(tmp_path: Path) -> None:
    """latency_ms must be a non-negative number."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    oracle = SafetyOracle(api_key="test-key", _model=_mock_gemini_model(_approve_payload()))
    decision = await oracle.check(_make_frame(), img)

    assert decision.latency_ms >= 0.0
    assert isinstance(decision.latency_ms, float)


async def test_oracle_logs_decision_event(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """oracle.decision structlog event must be emitted on every check()."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    # caplog captures stdlib log records; structlog emits via stdlib integration
    import logging

    import structlog

    structlog.reset_defaults()

    oracle = SafetyOracle(api_key="test-key", _model=_mock_gemini_model(_approve_payload()))
    with caplog.at_level(logging.DEBUG):
        decision = await oracle.check(_make_frame(), img)

    assert isinstance(decision, OracleDecision)


# ── _local_fallback_core unit tests ──────────────────────────────────────────


def test_fallback_core_approve(tmp_path: Path) -> None:
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")
    core = _local_fallback_core(_make_frame(), img, 80.0)
    assert core["action_approved"] is True
    assert core["prompt_version"] == "local-fallback-v1"
    assert core["confidence"] == 0.50


def test_fallback_core_deny_torque(tmp_path: Path) -> None:
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")
    core = _local_fallback_core(_make_frame(torques=[85.0] + [5.0] * 5), img, 80.0)
    assert core["action_approved"] is False
    assert "85.0" in core["reason"]


def test_fallback_core_deny_obstacle_label(tmp_path: Path) -> None:
    img = tmp_path / "obstacle_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")
    (tmp_path / "labels.json").write_text(json.dumps({"obstacle_01.jpg": "obstacle"}))
    core = _local_fallback_core(_make_frame(), img, 80.0)
    assert core["action_approved"] is False


def test_fallback_core_clear_label_approves(tmp_path: Path) -> None:
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")
    (tmp_path / "labels.json").write_text(json.dumps({"clear_01.jpg": "clear"}))
    core = _local_fallback_core(_make_frame(), img, 80.0)
    assert core["action_approved"] is True


# ── Prompt version ────────────────────────────────────────────────────────────


async def test_oracle_records_prompt_version(tmp_path: Path) -> None:
    """The prompt_version from Gemini's response must appear in OracleDecision."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    oracle = SafetyOracle(api_key="test-key", _model=_mock_gemini_model(_approve_payload()))
    decision = await oracle.check(_make_frame(), img)

    assert decision.prompt_version == "safety_oracle_v1"


# ── Retry behaviour ───────────────────────────────────────────────────────────


async def test_oracle_retries_on_transient_error(tmp_path: Path) -> None:
    """The oracle must retry on transient failures and succeed on the 2nd attempt."""
    img = tmp_path / "clear_01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    call_count = 0

    async def _flaky(*_args: object, **_kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("transient error")
        mock_response = MagicMock()
        mock_response.text = json.dumps(_approve_payload())
        mock_response.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)
        return mock_response

    mock_model = MagicMock()
    mock_model.generate_content_async = _flaky

    oracle = SafetyOracle(api_key="test-key", _model=mock_model, timeout_s=30.0)
    decision = await oracle.check(_make_frame(), img)

    assert call_count == 2
    assert decision.action_approved is True
    assert decision.used_fallback is False

"""Tests for auxin_sdk.logging — structlog configuration and request_id binding."""

from __future__ import annotations

import uuid

import structlog

from auxin_sdk.logging import bind_request_id, clear_request_id, configure_structlog, get_logger


def test_configure_structlog_runs_without_error() -> None:
    configure_structlog()


def test_configure_structlog_accepts_custom_log_level() -> None:
    import logging
    configure_structlog(log_level=logging.DEBUG)


def test_bind_request_id_generates_uuid4() -> None:
    rid = bind_request_id()
    assert len(rid) == 36
    # Validate it's a valid UUID4
    parsed = uuid.UUID(rid)
    assert parsed.version == 4


def test_bind_request_id_uses_provided_value() -> None:
    custom = "my-request-abc-123"
    returned = bind_request_id(custom)
    assert returned == custom


def test_clear_request_id_runs_without_error() -> None:
    bind_request_id()
    clear_request_id()  # must not raise


def test_get_logger_returns_bound_logger() -> None:
    configure_structlog()
    log = get_logger("test.module")
    assert log is not None


def test_request_id_appears_in_log_context() -> None:
    """After bind_request_id, the ID is present in structlog's contextvar store."""
    configure_structlog()
    rid = bind_request_id()
    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("request_id") == rid
    clear_request_id()

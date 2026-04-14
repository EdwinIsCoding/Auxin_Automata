"""Structured JSON logging with request_id context propagation via structlog.

Usage
-----
Call ``configure_structlog()`` once at process startup, then use
``get_logger(__name__)`` in every module.  Bind a request ID at the boundary
of each async task so it propagates through all log records in that context::

    from auxin_sdk.logging import configure_structlog, bind_request_id, get_logger

    configure_structlog()
    log = get_logger(__name__)

    async def handle_frame(frame):
        bind_request_id()          # generates a UUID4 and binds it
        log.info("frame.received", joints=len(frame.joint_positions))
"""

from __future__ import annotations

import logging
import uuid

import structlog


def configure_structlog(log_level: int = logging.INFO) -> None:
    """
    Configure structlog to emit newline-delimited JSON to stdout.

    Must be called once before any loggers are created.  Subsequent calls are
    safe but redundant (``cache_logger_on_first_use=True``).
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            # add_logger_name is omitted: it requires a stdlib Logger (.name attr)
            # which is incompatible with PrintLoggerFactory. Module name is available
            # via structlog.get_logger(__name__) binding instead.
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_request_id(request_id: str | None = None) -> str:
    """
    Bind a ``request_id`` field to the current async task's log context.

    If *request_id* is ``None``, a new UUID4 is generated.  The ID is returned
    so callers can propagate it (e.g. include it in on-chain transaction memos).

    This uses ``structlog.contextvars`` which is asyncio-safe: bindings are
    scoped to the current task and do not leak across tasks.
    """
    if request_id is None:
        request_id = str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    return request_id


def clear_request_id() -> None:
    """Clear all contextvars-bound log fields for the current async task."""
    structlog.contextvars.clear_contextvars()


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """Return a structlog BoundLogger for *name*."""
    return structlog.get_logger(name)

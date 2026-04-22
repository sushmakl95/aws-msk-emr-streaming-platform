"""Structured logging."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configure structlog globally."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(message)s",
        stream=sys.stdout,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if fmt == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


configure_logging(
    level=os.environ.get("STREAMING_LOG_LEVEL", "INFO"),
    fmt=os.environ.get("STREAMING_LOG_FORMAT", "console"),
)


def get_logger(name: str, **bindings):
    return structlog.get_logger(name).bind(**bindings)

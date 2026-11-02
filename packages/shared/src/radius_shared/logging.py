"""Structured logging helpers."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from radius_shared.config import LogLevel
from radius_shared.observability.context import get_correlation_context
from radius_shared.observability.tracing import current_trace_id
from radius_shared.redaction import redact_secrets, redact_structure

_STANDARD_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    """Format log records as compact JSON objects.

    Message, exception text, and string ``extra`` fields are passed through
    :func:`radius_shared.redaction.redact_secrets` so a token echoed in an
    error message never reaches the log sink.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
        }

        if record.exc_info:
            payload["exception"] = redact_secrets(self.formatException(record.exc_info))
        # Correlation ids from contextvars; explicit ``extra`` wins below.
        payload.update(get_correlation_context())
        trace_id = current_trace_id()
        if trace_id is not None:
            payload["trace_id"] = trace_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                payload[key] = redact_structure(value, key=key)

        return json.dumps(payload, separators=(",", ":"), default=str)


class RedactingFilter(logging.Filter):
    """Scrub secrets from a record's message, args and extras in place.

    The JSON formatter already redacts its output; this filter protects any
    other handler attached to the same logger (plain text, third-party).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = None
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                setattr(record, key, redact_structure(value, key=key))
        return True


def configure_logging(level: LogLevel | str = LogLevel.INFO) -> None:
    """Configure process-level structured logging."""

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(str(level).upper())

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""

    return logging.getLogger(name)

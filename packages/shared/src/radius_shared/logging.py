"""Structured logging helpers."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from radius_shared.config import LogLevel

_STANDARD_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    """Format log records as compact JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(level: LogLevel | str = LogLevel.INFO) -> None:
    """Configure process-level structured logging."""

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(str(level))

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""

    return logging.getLogger(name)

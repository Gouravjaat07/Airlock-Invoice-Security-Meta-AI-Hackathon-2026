"""Structured logging without secrets.

JSON lines on stdout with request_id/case_id context. Secret-shaped
values are redacted by key name before emission.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

REDACTED_KEYS = frozenset({
    "pin", "pin_hash", "session_token", "session_secret", "csrf_token",
    "bank_account", "bank_reference", "account_number", "api_key",
    "authorization", "cookie", "set-cookie",
})

_logger = logging.getLogger("airlock")


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: ("***" if str(key).lower() in REDACTED_KEYS else _redact(value))
            for key, value in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(item) for item in obj]
    return obj


class _JsonHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        payload = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload["context"] = _redact(context)
        try:
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass


def configure_logging(level: str = "INFO") -> None:
    _logger.handlers.clear()
    _logger.addHandler(_JsonHandler())
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    _logger.propagate = False


def get_logger(name: str = "airlock") -> logging.Logger:
    # Plain logger (not LoggerAdapter): since Python 3.13 an adapter
    # overwrites per-call `extra` with its own, which would drop context.
    return logging.getLogger(name)


def log(logger: logging.Logger, level: int, message: str, **context: Any) -> None:
    logger.log(level, message, extra={"context": _redact(context)})

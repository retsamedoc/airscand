"""Structured logging configuration utilities."""

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON payloads."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize record payload including non-standard extra fields."""
        payload = {
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
            }
        }
        payload.update(extras)
        return json.dumps(payload, default=str)

def _resolve_log_level(level_name: str) -> int:
    """Resolve string level names to standard logging levels."""
    return getattr(logging, level_name.upper(), logging.INFO)


def setup_logging(level_name: str = "INFO") -> None:
    """Configure root logger with JSON formatter on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(_resolve_log_level(level_name))
    root.addHandler(handler)

"""Structured logging configuration utilities."""

from __future__ import annotations

import json
import logging
import os
import sys

import coloredlogs

# Keys from ``extra={...}`` appended to INFO+ human lines (order preserved).
LOG_INLINE_CONTEXT_KEYS: tuple[str, ...] = (
    "scanner_xaddr",
    "subscribe_to_url",
    "get_to_url",
    "subscription_id",
    "subscribe_destination_token",
    "expires",
    "soap_leg",
    "soap_action",
    "http_status",
    "wsa_message_id",
    "url",
    "fault_subcode",
    "fault_reason",
)


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


def _env_bool(name: str, default: bool) -> bool:
    """Parse common truthy/falsey environment variable values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _use_color() -> bool:
    """Respect NO_COLOR and terminal capability."""
    if os.environ.get("NO_COLOR"):
        return False
    return bool(coloredlogs.terminal_supports_colors(sys.stdout))


def _inline_context_suffix(record: logging.LogRecord) -> str:
    """Build `` | key=value ...`` for whitelisted extras present on the record."""
    parts: list[str] = []
    for key in LOG_INLINE_CONTEXT_KEYS:
        if key not in record.__dict__:
            continue
        value = record.__dict__[key]
        if value is None:
            continue
        parts.append(f"{key}={value}")
    if not parts:
        return ""
    return " | " + " ".join(parts)


class AirscandConsoleFormatter(logging.Formatter):
    """Emit JSON for DEBUG; human ``%(asctime)s %(module)s %(message)s`` for INFO+."""

    def __init__(self, *, use_color: bool) -> None:
        super().__init__()
        self._json = JsonFormatter()
        datefmt = "%Y-%m-%d %H:%M:%S"
        fmt = "%(asctime)s %(module)s %(message)s"
        if use_color:
            self._human: logging.Formatter = coloredlogs.ColoredFormatter(fmt=fmt, datefmt=datefmt)
        else:
            self._human = logging.Formatter(fmt=fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        """Format DEBUG as JSON; otherwise human line with optional inline context."""
        if record.levelno == logging.DEBUG:
            return self._json.format(record)
        line = self._human.format(record)
        return line + _inline_context_suffix(record)


def _resolve_log_level(level_name: str) -> int:
    """Resolve string level names to standard logging levels."""
    return getattr(logging, level_name.upper(), logging.INFO)


def setup_logging(level_name: str = "INFO", *, log_json: bool | None = None) -> None:
    """Configure root logger on stdout.

    If ``log_json`` is true or env ``WSD_LOG_JSON`` is truthy, all levels use
    :class:`JsonFormatter`. Otherwise DEBUG uses JSON and INFO+ use a colored
    (when supported) human line with optional inline context from
    :data:`LOG_INLINE_CONTEXT_KEYS`.
    """
    use_json = _env_bool("WSD_LOG_JSON", False) if log_json is None else log_json

    handler = logging.StreamHandler(sys.stdout)
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(AirscandConsoleFormatter(use_color=_use_color()))

    root = logging.getLogger()
    root.setLevel(_resolve_log_level(level_name))
    root.addHandler(handler)

"""Structured logging configuration utilities."""

from __future__ import annotations

import json
import logging
import os
import sys

import coloredlogs
from humanfriendly.terminal import ansi_wrap

# Keys from ``extra={...}`` appended to INFO+ human lines (order preserved).
LOG_INLINE_CONTEXT_KEYS: tuple[str, ...] = (
    "scanner_xaddr",
    "subscribe_to_url",
    "subscription_manager_url",
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

# Human console: max line width (visible characters); clamped in :func:`_human_wrap_width`.
LOG_WRAP_WIDTH_DEFAULT: int = 120
LOG_WRAP_WIDTH_MIN: int = 40
# Fixed column width for ``%(module)s`` in human lines (truncate with ellipsis if longer).
MODULE_COLUMN_WIDTH: int = 16


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


def _human_wrap_width() -> int:
    """Resolve ``WSD_LOG_WRAP_WIDTH`` (default :data:`LOG_WRAP_WIDTH_DEFAULT`)."""
    raw = os.getenv("WSD_LOG_WRAP_WIDTH")
    if raw is None:
        return LOG_WRAP_WIDTH_DEFAULT
    try:
        w = int(raw.strip())
    except ValueError:
        return LOG_WRAP_WIDTH_DEFAULT
    return max(LOG_WRAP_WIDTH_MIN, w)


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


def _module_column(name: str, width: int = MODULE_COLUMN_WIDTH) -> str:
    """Left-align ``name`` in a fixed-width column; truncate with an ellipsis if needed."""
    if len(name) <= width:
        return name.ljust(width)
    if width < 2:
        return name[:width]
    return name[: width - 1] + "…"


def _wrap_words_line(text: str, line_width: int) -> list[str]:
    """Split ``text`` into lines at most ``line_width`` characters, breaking at whitespace only."""
    if line_width < 1:
        line_width = 1
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    current_len = 0
    for w in words:
        extra = len(w) + (1 if current else 0)
        if current_len + extra <= line_width:
            current.append(w)
            current_len += extra
        else:
            if current:
                lines.append(" ".join(current))
            if len(w) > line_width:
                lines.append(w)
                current = []
                current_len = 0
            else:
                current = [w]
                current_len = len(w)
    if current:
        lines.append(" ".join(current))
    return lines


def _wrap_human_plain(prefix: str, body: str, width: int) -> str:
    """Wrap ``body`` under ``prefix`` so each output line is at most ``width`` characters."""
    plen = len(prefix)
    avail = max(1, width - plen)
    indent = " " * plen
    paragraphs = body.split("\n")
    result_lines: list[str] = []
    first_global = True
    for para in paragraphs:
        chunks = _wrap_words_line(para, avail) if para else []
        if not chunks:
            if para == "":
                if result_lines:
                    result_lines.append("")
                continue
            chunks = [""]
        for chunk in chunks:
            if first_global:
                result_lines.append(prefix + chunk)
                first_global = False
            else:
                result_lines.append(indent + chunk)
    return "\n".join(result_lines)


def _apply_level_message_style(
    text: str,
    record: logging.LogRecord,
    level_styles: dict[str, dict[str, object]],
    name_normalizer: coloredlogs.NameNormalizer,
) -> str:
    """Apply coloredlogs level styling to message text (matches :class:`coloredlogs.ColoredFormatter`)."""
    style = name_normalizer.get(level_styles, record.levelname)
    if not style:
        return text
    return ansi_wrap(text, **style)


class AirscandConsoleFormatter(logging.Formatter):
    """Emit JSON for DEBUG; human ``%(asctime)s %(module)s %(message)s`` for INFO+."""

    def __init__(self, *, use_color: bool) -> None:
        super().__init__()
        self._json = JsonFormatter()
        self._datefmt = "%Y-%m-%d %H:%M:%S"
        self._use_color = use_color
        if use_color:
            self._cf = coloredlogs.ColoredFormatter(
                fmt="%(asctime)s %(module)s %(message)s",
                datefmt=self._datefmt,
            )
        else:
            self._cf = None

    def _format_human_plain(self, record: logging.LogRecord) -> str:
        """Build a plain-text human record (timestamp, module column, message, optional traceback)."""
        asctime = self.formatTime(record, self._datefmt)
        mod = _module_column(record.module)
        prefix = f"{asctime} {mod} "
        body = record.getMessage() + _inline_context_suffix(record)
        if _env_bool("WSD_LOG_WRAP", True):
            main = _wrap_human_plain(prefix, body, _human_wrap_width())
        else:
            main = prefix + body
        if record.exc_info and record.exc_text:
            return main + "\n" + record.exc_text
        return main

    def _colorize_human_head(self, head: str, record: logging.LogRecord) -> str:
        """Apply field and level ANSI styling to wrapped human text (no traceback)."""
        assert self._cf is not None
        asctime = self.formatTime(record, self._datefmt)
        mod = _module_column(record.module)
        prefix_plain = f"{asctime} {mod} "
        plen = len(prefix_plain)
        indent_plain = " " * plen
        asctime_style = coloredlogs.DEFAULT_FIELD_STYLES.get("asctime") or {}
        lines = head.split("\n")
        out: list[str] = []
        for i, line in enumerate(lines):
            if i == 0:
                if not line.startswith(prefix_plain):
                    return head
                msg_part = line[plen:]
                out.append(
                    ansi_wrap(asctime, **asctime_style)
                    + " "
                    + mod
                    + " "
                    + _apply_level_message_style(
                        msg_part,
                        record,
                        self._cf.level_styles,
                        self._cf.nn,
                    )
                )
            elif line == "":
                out.append("")
            elif line.startswith(indent_plain):
                cont = line[plen:]
                out.append(
                    indent_plain
                    + _apply_level_message_style(
                        cont,
                        record,
                        self._cf.level_styles,
                        self._cf.nn,
                    )
                )
            else:
                out.append(line)
        return "\n".join(out)

    def _colorize_human(self, main: str, record: logging.LogRecord) -> str:
        """Apply the same field and level ANSI styling as :class:`coloredlogs.ColoredFormatter`."""
        assert self._cf is not None
        if record.exc_info:
            idx = main.find("\nTraceback")
            if idx != -1:
                head, tail = main[:idx], main[idx + 1 :]
                return self._colorize_human_head(head, record) + "\n" + tail
        return self._colorize_human_head(main, record)

    def format(self, record: logging.LogRecord) -> str:
        """Format DEBUG as JSON; otherwise human lines with optional wrap and inline context."""
        if record.levelno == logging.DEBUG:
            return self._json.format(record)
        if record.exc_info:
            if record.exc_text is None:
                record.exc_text = self.formatException(record.exc_info)
        main = self._format_human_plain(record)
        if self._use_color and self._cf is not None:
            return self._colorize_human(main, record)
        return main


def _resolve_log_level(level_name: str) -> int:
    """Resolve string level names to standard logging levels."""
    return getattr(logging, level_name.upper(), logging.INFO)


def setup_logging(level_name: str = "INFO", *, log_json: bool | None = None) -> None:
    """Configure root logger on stdout.

    If ``log_json`` is true or env ``WSD_LOG_JSON`` is truthy, all levels use
    :class:`JsonFormatter`. Otherwise DEBUG uses JSON and INFO+ use a colored
    (when supported) human line with optional inline context from
    :data:`LOG_INLINE_CONTEXT_KEYS`.

    Human line width is controlled by ``WSD_LOG_WRAP`` (default on) and
    ``WSD_LOG_WRAP_WIDTH`` (default 120, minimum 40).
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

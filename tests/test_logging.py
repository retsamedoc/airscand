"""Logging configuration tests."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from app.logging import MODULE_COLUMN_WIDTH

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

# ``%(asctime)s`` with ``%Y-%m-%d %H:%M:%S`` is always 19 characters.
_TIMESTAMP_LEN = 19
# Indent for wrapped human lines matches ``formatTime + ' ' + module column + ' '``.
_EXPECTED_PREFIX_LEN = _TIMESTAMP_LEN + 1 + MODULE_COLUMN_WIDTH + 1

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI color sequences for stable assertions."""
    return _ANSI_ESCAPE.sub("", text)


def test_setup_logging_emits_human_line_by_default(capsys: CaptureFixture[str]) -> None:
    """Default mode logs INFO as a human line with %(module)s."""
    root = logging.getLogger()
    root.handlers.clear()

    from app.logging import setup_logging

    setup_logging()
    logging.getLogger("airscand.test").info("hello")

    captured = capsys.readouterr()
    line = _strip_ansi(captured.out.strip().splitlines()[-1])

    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", line)
    assert re.search(r"test_logging\s+hello$", line)


def test_setup_logging_appends_inline_context(capsys: CaptureFixture[str]) -> None:
    """Whitelisted extras appear as key=value suffix on INFO lines."""
    root = logging.getLogger()
    root.handlers.clear()

    from app.logging import setup_logging

    setup_logging()
    logging.getLogger("airscand.test").info(
        "event",
        extra={"scanner_xaddr": "http://192.168.1.1/WSD/DEVICE"},
    )

    captured = capsys.readouterr()
    line = _strip_ansi(captured.out.strip().splitlines()[-1])

    assert "scanner_xaddr=http://192.168.1.1/WSD/DEVICE" in line


def test_setup_logging_debug_emits_json(capsys: CaptureFixture[str]) -> None:
    """Console mode emits DEBUG records as JSON."""
    root = logging.getLogger()
    root.handlers.clear()

    from app.logging import setup_logging

    setup_logging("DEBUG")
    logging.getLogger("airscand.test").debug("debug hello")

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["level"] == "DEBUG"
    assert payload["message"] == "debug hello"
    assert "module" in payload


def test_setup_logging_log_json_forces_json_for_info(
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    """WSD_LOG_JSON=1 keeps machine-readable JSON for all levels."""
    root = logging.getLogger()
    root.handlers.clear()

    monkeypatch.setenv("WSD_LOG_JSON", "1")

    from app.logging import setup_logging

    setup_logging()
    logging.getLogger("airscand.test").info("hello json")

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["level"] == "INFO"
    assert payload["message"] == "hello json"


def test_setup_logging_log_json_kwarg(capsys: CaptureFixture[str]) -> None:
    """``log_json=True`` matches env-based JSON mode."""
    root = logging.getLogger()
    root.handlers.clear()

    from app.logging import setup_logging

    setup_logging(log_json=True)
    logging.getLogger("airscand.test").info("kwarg json")

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["message"] == "kwarg json"


def test_setup_logging_wraps_long_message_at_word_boundary(
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    """INFO lines wrap at ``WSD_LOG_WRAP_WIDTH`` with continuation under the message column."""
    root = logging.getLogger()
    root.handlers.clear()

    monkeypatch.setenv("WSD_LOG_WRAP", "1")
    monkeypatch.setenv("WSD_LOG_WRAP_WIDTH", "80")
    monkeypatch.setenv("NO_COLOR", "1")

    from app.logging import setup_logging

    setup_logging()
    long_msg = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo "
        "lima mike november oscar papa quebec romeo sierra tango uniform victor"
    )
    logging.getLogger("airscand.test").info(long_msg)

    captured = capsys.readouterr()
    lines = [_strip_ansi(ln) for ln in captured.out.strip().splitlines()]
    assert len(lines) >= 2
    assert lines[1].startswith(" " * _EXPECTED_PREFIX_LEN)
    for ln in lines:
        assert len(ln) <= 80 or ln.split() == [ln.split()[0]]


def test_setup_logging_wrap_disabled_single_line(
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    """``WSD_LOG_WRAP=0`` keeps a long message on one line."""
    root = logging.getLogger()
    root.handlers.clear()

    monkeypatch.setenv("WSD_LOG_WRAP", "0")
    monkeypatch.setenv("NO_COLOR", "1")

    from app.logging import setup_logging

    setup_logging()
    long_msg = "word " * 40 + "end"
    logging.getLogger("airscand.test").info(long_msg)

    captured = capsys.readouterr()
    lines = [_strip_ansi(ln) for ln in captured.out.strip().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert "word" in lines[0]


def test_setup_logging_long_token_may_exceed_width(
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    """A single token longer than the wrap width is not split; that line may exceed the limit."""
    root = logging.getLogger()
    root.handlers.clear()

    monkeypatch.setenv("WSD_LOG_WRAP_WIDTH", "60")
    monkeypatch.setenv("NO_COLOR", "1")

    from app.logging import setup_logging

    setup_logging()
    token = "x" * 70
    logging.getLogger("airscand.test").info(token)

    captured = capsys.readouterr()
    lines = [_strip_ansi(ln) for ln in captured.out.strip().splitlines()]
    assert any(len(ln) > 60 for ln in lines)


def test_setup_logging_wrap_preserves_paragraph_newlines(
    capsys: CaptureFixture[str],
    monkeypatch: MonkeyPatch,
) -> None:
    """Embedded newlines in the message produce blank lines between wrapped paragraphs."""
    root = logging.getLogger()
    root.handlers.clear()

    monkeypatch.setenv("WSD_LOG_WRAP_WIDTH", "120")
    monkeypatch.setenv("NO_COLOR", "1")

    from app.logging import setup_logging

    setup_logging()
    logging.getLogger("airscand.test").info("first block words here\n\nsecond block after blank")

    captured = capsys.readouterr()
    text = _strip_ansi(captured.out)
    assert "\n\n" in text

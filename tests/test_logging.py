"""Logging configuration tests."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

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
    assert line.endswith(" test_logging hello")


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

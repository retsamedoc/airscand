import json
import logging


def test_setup_logging_emits_json(capsys):
    root = logging.getLogger()
    root.handlers.clear()

    from app.logging import setup_logging

    setup_logging()
    logging.getLogger("airscand.test").info("hello")

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert "module" in payload


def test_setup_logging_honors_debug_level(capsys):
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


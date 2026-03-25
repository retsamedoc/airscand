import re


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("WSD_HOST", "127.0.0.1")
    monkeypatch.setenv("WSD_PORT", "1234")
    monkeypatch.setenv("WSD_ENDPOINT", "/x")
    monkeypatch.setenv("WSD_SCAN_PATH", "/y")
    monkeypatch.setenv("WSD_OUTPUT_DIR", "/tmp/scans")
    monkeypatch.setenv("WSD_ADVERTISE_ADDR", "192.168.1.50")
    monkeypatch.setenv("WSD_UUID", "explicit-uuid")

    from app.config import Config

    cfg = Config()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 1234
    assert cfg.endpoint_path == "/x"
    assert cfg.scan_path == "/y"
    assert cfg.output_dir == "/tmp/scans"
    assert cfg.advertise_addr == "192.168.1.50"
    assert cfg.uuid == "explicit-uuid"


def test_config_persistent_uuid(monkeypatch, tmp_path):
    monkeypatch.delenv("WSD_UUID", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    from app.config import Config

    cfg1 = Config()
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", cfg1.uuid)

    cfg2 = Config()
    assert cfg2.uuid == cfg1.uuid


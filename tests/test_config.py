import re


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("WSD_HOST", "127.0.0.1")
    monkeypatch.setenv("WSD_PORT", "1234")
    monkeypatch.setenv("WSD_ENDPOINT", "/x")
    monkeypatch.setenv("WSD_SCAN_PATH", "/y")
    monkeypatch.setenv("WSD_OUTPUT_DIR", "/tmp/scans")
    monkeypatch.setenv("WSD_ADVERTISE_ADDR", "192.168.1.50")
    monkeypatch.setenv("WSD_UUID", "explicit-uuid")
    monkeypatch.setenv("WSD_SCANNER_XADDR", "http://192.168.1.60:80/WSD/DEVICE")
    monkeypatch.setenv("WSD_LOG_LEVEL", "debug")
    monkeypatch.setenv("WSD_SCANNER_SUBSCRIBE_TO_URL", "http://192.168.1.60:80/WSDScanner")
    monkeypatch.setenv("WSD_EVENTING_PREFLIGHT_GET", "0")
    monkeypatch.setenv("WSD_EVENTING_NOTIFY_TO_URL", "http://192.168.1.50:5357/callback")

    from app.config import Config

    cfg = Config()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 1234
    assert cfg.endpoint_path == "/x"
    assert cfg.scan_path == "/y"
    assert cfg.output_dir == "/tmp/scans"
    assert cfg.advertise_addr == "192.168.1.50"
    assert cfg.uuid == "explicit-uuid"
    assert cfg.scanner_xaddr == "http://192.168.1.60:80/WSD/DEVICE"
    assert cfg.log_level == "DEBUG"
    assert cfg.scanner_subscribe_to_url == "http://192.168.1.60:80/WSDScanner"
    assert cfg.eventing_preflight_get is False
    assert cfg.eventing_notify_to_url == "http://192.168.1.50:5357/callback"


def test_config_persistent_uuid(monkeypatch, tmp_path):
    monkeypatch.delenv("WSD_UUID", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    from app.config import Config

    cfg1 = Config()
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", cfg1.uuid)

    cfg2 = Config()
    assert cfg2.uuid == cfg1.uuid


def test_config_persistent_sequence_id(monkeypatch, tmp_path):
    monkeypatch.delenv("WSD_APP_SEQUENCE_SEQUENCE_ID", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("WSD_UUID", "explicit-uuid")

    from app.config import Config

    cfg1 = Config()
    assert cfg1.app_sequence_sequence_id.startswith("urn:uuid:")
    cfg2 = Config()
    assert cfg2.app_sequence_sequence_id == cfg1.app_sequence_sequence_id


def test_config_discovery_env_overrides(monkeypatch):
    monkeypatch.setenv("WSD_HELLO_INTERVAL_SEC", "0")
    monkeypatch.setenv("WSD_METADATA_VERSION", "7")
    monkeypatch.setenv("WSD_APP_SEQUENCE_INSTANCE_ID", "99")
    monkeypatch.setenv("WSD_APP_SEQUENCE_SEQUENCE_ID", "urn:uuid:fixed-seq")

    from app.config import Config

    cfg = Config()
    assert cfg.hello_interval_sec == 0.0
    assert cfg.metadata_version == 7
    assert cfg.app_sequence_instance_id == 99
    assert cfg.app_sequence_sequence_id == "urn:uuid:fixed-seq"


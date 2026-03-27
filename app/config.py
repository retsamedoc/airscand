from dataclasses import dataclass
import os
from pathlib import Path
import socket
import uuid as uuidlib

@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 5357
    endpoint_path: str = "/wsd"
    scan_path: str = "/scan"
    output_dir: str = "./scans"
    advertise_addr: str = ""
    uuid: str = ""
    hello_interval_sec: float = 60.0
    metadata_version: int = 1
    app_sequence_instance_id: int = 1
    app_sequence_sequence_id: str = ""
    scanner_xaddr: str = ""
    log_level: str = "INFO"
    scanner_subscribe_to_url: str = ""
    eventing_preflight_get: bool = True
    eventing_notify_to_url: str = ""

    def __post_init__(self) -> None:
        self.host = os.getenv("WSD_HOST", self.host)
        self.port = int(os.getenv("WSD_PORT", str(self.port)))
        self.endpoint_path = os.getenv("WSD_ENDPOINT", self.endpoint_path)
        self.scan_path = os.getenv("WSD_SCAN_PATH", self.scan_path)
        self.output_dir = os.getenv("WSD_OUTPUT_DIR", self.output_dir)
        self.advertise_addr = os.getenv("WSD_ADVERTISE_ADDR", self.advertise_addr).strip()
        raw_hello = os.getenv("WSD_HELLO_INTERVAL_SEC")
        if raw_hello is not None:
            self.hello_interval_sec = float(raw_hello)
        raw_meta = os.getenv("WSD_METADATA_VERSION")
        if raw_meta is not None:
            self.metadata_version = int(raw_meta)
        raw_inst = os.getenv("WSD_APP_SEQUENCE_INSTANCE_ID")
        if raw_inst is not None:
            self.app_sequence_instance_id = int(raw_inst)

        if not self.advertise_addr:
            if self.host and self.host != "0.0.0.0":
                self.advertise_addr = self.host
            else:
                self.advertise_addr = _detect_lan_ip()

        explicit_uuid = os.getenv("WSD_UUID")
        if explicit_uuid:
            self.uuid = explicit_uuid
        else:
            self.uuid = _get_or_create_persistent_uuid()

        self.app_sequence_sequence_id = os.getenv(
            "WSD_APP_SEQUENCE_SEQUENCE_ID", self.app_sequence_sequence_id
        ).strip()
        if not self.app_sequence_sequence_id:
            self.app_sequence_sequence_id = _get_or_create_sequence_id()

        self.scanner_xaddr = os.getenv("WSD_SCANNER_XADDR", self.scanner_xaddr).strip()
        self.log_level = os.getenv("WSD_LOG_LEVEL", self.log_level).strip().upper()
        self.scanner_subscribe_to_url = os.getenv(
            "WSD_SCANNER_SUBSCRIBE_TO_URL", self.scanner_subscribe_to_url
        ).strip()
        self.eventing_preflight_get = _env_bool(
            "WSD_EVENTING_PREFLIGHT_GET",
            self.eventing_preflight_get,
        )
        self.eventing_notify_to_url = os.getenv(
            "WSD_EVENTING_NOTIFY_TO_URL",
            self.eventing_notify_to_url,
        ).strip()


def _get_or_create_persistent_uuid() -> str:
    state_home = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    path = state_home / "airscand" / "uuid"

    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass

    new_uuid = str(uuidlib.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_uuid + "\n", encoding="utf-8")
    return new_uuid


def _get_or_create_sequence_id() -> str:
    state_home = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    path = state_home / "airscand" / "ws_discovery_sequence_id"

    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass

    sid = f"urn:uuid:{uuidlib.uuid4()}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sid + "\n", encoding="utf-8")
    return sid


def _detect_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are sent, but connect lets us infer an outbound local IP.
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")

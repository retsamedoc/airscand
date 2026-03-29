"""Configuration loading from environment variables and persisted state."""

import os
import socket
import uuid as uuidlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Runtime configuration resolved from defaults and environment variables."""

    host: str = "0.0.0.0"
    port: int = 5357
    endpoint_path: str = "/wsd"
    scan_path: str = "/scan"
    output_dir: str = "./scans"
    advertise_addr: str = ""
    uuid: str = ""
    hello_interval_sec: float = 60.0
    # Last WS-Discovery Hello AppSequence MessageNumber sent (for Bye sequencing).
    discovery_last_message_number: int = -1
    metadata_version: int = 1
    app_sequence_instance_id: int = 1
    app_sequence_sequence_id: str = ""
    scanner_xaddr: str = ""
    # SubscribeResponse Identifier (wsman:Identifier); optional CreateScanJob DestinationToken fallback.
    scanner_eventing_subscription_id: str = ""
    # DestinationToken from SubscribeResponse DestinationResponses (spec-primary for device-initiated scans).
    scanner_subscribe_destination_token: str = ""
    # ClientContext -> DestinationToken from SubscribeResponse (multi-destination); selection uses ScanAvailableEvent ClientContext.
    scanner_subscribe_destination_tokens: dict[str, str] = field(default_factory=dict)
    # True when WSD_SUBSCRIBE_DESTINATION_TOKEN env is set; forces single token until registration clears it.
    use_env_subscribe_destination_token_only: bool = False
    # Logging: ``WSD_LOG_LEVEL`` sets the root level (default INFO).
    # ``WSD_LOG_JSON`` when true emits JSON for every level; when false, INFO+ use human lines and DEBUG uses JSON only.
    log_level: str = "INFO"
    log_json: bool = False
    scanner_subscribe_to_url: str = ""
    # Subscription Manager ``wsa:Address`` from SubscribeResponse (outbound Unsubscribe/Renew/GetStatus).
    scanner_eventing_subscribe_manager_url: str = ""
    # Optional ``wsa:ReferenceParameters`` element XML from ``SubscriptionManager`` in SubscribeResponse.
    scanner_eventing_subscribe_manager_reference_parameters_xml: str = ""
    # Second subscription (ScannerStatusSummaryEvent): manager EPR from that SubscribeResponse.
    scanner_eventing_subscribe_manager_url_status: str = ""
    scanner_eventing_subscribe_manager_reference_parameters_xml_status: str = ""
    eventing_preflight_get: bool = True
    eventing_notify_to_url: str = ""
    # When CreateScanJob fails with ClientErrorInvalidDestinationToken, retry once without DestinationToken.
    create_scan_job_retry_invalid_destination_token: bool = True
    # Second WS-Eventing subscription id for ScannerStatusSummaryEvent (optional).
    scanner_eventing_subscription_id_status: str = ""
    # After successful RetrieveImage, wait for inbound ScannerStatusSummaryEvent Idle (global state).
    wait_scanner_idle_after_retrieve: bool = True
    scanner_idle_wait_sec: float = 60.0
    # ``app.quirks.get_profile`` key (e.g. generic, epson_wf_3640); skeleton until post–Phase 5.
    scanner_profile: str = "epson_wf_3640"
    # Large MTOM transfers from RetrieveImage can take significantly longer than SOAP control calls.
    retrieve_image_timeout_sec: float = 120.0

    def __post_init__(self) -> None:
        """Resolve environment variables and derive runtime values."""
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
        self.scanner_eventing_subscription_id = os.getenv(
            "WSD_EVENTING_SUBSCRIPTION_ID", self.scanner_eventing_subscription_id
        ).strip()
        self.scanner_subscribe_destination_token = os.getenv(
            "WSD_SUBSCRIBE_DESTINATION_TOKEN", self.scanner_subscribe_destination_token
        ).strip()
        self.use_env_subscribe_destination_token_only = bool(
            os.getenv("WSD_SUBSCRIBE_DESTINATION_TOKEN", "").strip()
        )
        self.log_level = os.getenv("WSD_LOG_LEVEL", self.log_level).strip().upper()
        self.log_json = _env_bool("WSD_LOG_JSON", self.log_json)
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
        self.create_scan_job_retry_invalid_destination_token = _env_bool(
            "WSD_CREATE_SCAN_JOB_RETRY_INVALID_DESTINATION_TOKEN",
            self.create_scan_job_retry_invalid_destination_token,
        )
        self.scanner_eventing_subscription_id_status = os.getenv(
            "WSD_EVENTING_SUBSCRIPTION_ID_STATUS",
            self.scanner_eventing_subscription_id_status,
        ).strip()
        self.wait_scanner_idle_after_retrieve = _env_bool(
            "WSD_WAIT_SCANNER_IDLE_AFTER_RETRIEVE",
            self.wait_scanner_idle_after_retrieve,
        )
        raw_idle = os.getenv("WSD_SCANNER_IDLE_WAIT_SEC")
        if raw_idle is not None and raw_idle.strip() != "":
            self.scanner_idle_wait_sec = float(raw_idle.strip())
        self.scanner_profile = os.getenv("WSD_SCANNER_PROFILE", self.scanner_profile).strip()
        raw_retrieve = os.getenv("WSD_RETRIEVE_IMAGE_TIMEOUT_SEC")
        if raw_retrieve is not None and raw_retrieve.strip() != "":
            self.retrieve_image_timeout_sec = float(raw_retrieve.strip())


def _get_or_create_persistent_uuid() -> str:
    """Load UUID from state file, or create and persist a new one."""
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
    """Load app sequence id from state file, or create a new one."""
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
    """Best-effort LAN IP detection for outbound interface selection."""
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
    """Parse common truthy/falsey environment variable values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")

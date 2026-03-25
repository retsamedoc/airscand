from dataclasses import dataclass
import os
from pathlib import Path
import uuid as uuidlib

@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 5357
    endpoint_path: str = "/wsd"
    scan_path: str = "/scan"
    output_dir: str = "./scans"
    uuid: str = ""

    def __post_init__(self) -> None:
        self.host = os.getenv("WSD_HOST", self.host)
        self.port = int(os.getenv("WSD_PORT", str(self.port)))
        self.endpoint_path = os.getenv("WSD_ENDPOINT", self.endpoint_path)
        self.scan_path = os.getenv("WSD_SCAN_PATH", self.scan_path)
        self.output_dir = os.getenv("WSD_OUTPUT_DIR", self.output_dir)

        explicit_uuid = os.getenv("WSD_UUID")
        if explicit_uuid:
            self.uuid = explicit_uuid
            return

        self.uuid = _get_or_create_persistent_uuid()


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

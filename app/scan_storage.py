"""Shared scan file persistence and type detection.

Used by both push uploads (`/scan`) and pull transfers (WS-Scan RetrieveImage MTOM).
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

__all__ = [
    "detect_file_type",
    "extension_from_mime",
    "write_scan_atomically",
    "save_scan_file",
]

log = logging.getLogger(__name__)


def detect_file_type(data: bytes) -> str:
    """Infer output file extension from leading content bytes."""
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data.startswith(b"%PDF"):
        return "pdf"
    return "bin"


def extension_from_mime(content_type: str | None) -> str | None:
    """Map MIME type (or full Content-Type value) to a file extension, if known."""
    if not content_type:
        return None
    main = content_type.split(";", 1)[0].strip().lower()
    table = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/pjpeg": "jpg",
        "image/png": "png",
        "image/tiff": "tif",
        "image/tif": "tif",
        "application/pdf": "pdf",
        "application/octet-stream": None,
    }
    return table.get(main)


def write_scan_atomically(output_path: Path, data: bytes) -> None:
    """Persist scan bytes via temp file + atomic replace."""
    tmp_path = output_path.with_name(f".{output_path.name}.part")
    try:
        with tmp_path.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(output_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def save_scan_file(output_dir: Path, data: bytes, *, content_type: str | None = None) -> Path:
    """Write scan bytes under ``output_dir`` with a unique name; prefer MIME for extension."""
    ext = extension_from_mime(content_type) or detect_file_type(data)
    filename = f"scan_{uuid.uuid4()}.{ext}"
    path = output_dir / filename
    output_dir.mkdir(parents=True, exist_ok=True)
    write_scan_atomically(path, data)
    log.info(
        "Scan saved",
        extra={
            "file": str(path),
            "bytes": len(data),
            "content_type": content_type,
            "detected_ext": ext,
        },
    )
    return path


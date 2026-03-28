"""Inbound scan receiver and persistence helpers."""

import logging
import os
import uuid
from pathlib import Path

from aiohttp import web

from app.config import Config

__all__ = ["handle_scan", "detect_file_type"]

log = logging.getLogger(__name__)


def detect_file_type(data: bytes) -> str:
    """Infer output file extension from leading content bytes."""
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data.startswith(b"%PDF"):
        return "pdf"
    return "bin"


def _write_scan_atomically(output_path: Path, data: bytes) -> None:
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


async def handle_scan(request: web.Request) -> web.Response:
    """Store uploaded scan payload to configured output directory."""
    data = await request.read()
    if not data:
        log.warning(
            "Rejected empty scan payload",
            extra={"content_type": request.content_type, "content_length": request.content_length},
        )
        return web.Response(status=400, text="Empty scan payload")

    ext = detect_file_type(data)
    filename = f"scan_{uuid.uuid4()}.{ext}"

    config = request.app.get("config")
    if not isinstance(config, Config):
        log.error("Scan request missing valid config object")
        return web.Response(status=500, text="Server configuration unavailable")
    output_dir = Path(getattr(config, "output_dir", "./scans"))

    path = output_dir / filename
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_scan_atomically(path, data)
    except OSError:
        log.exception(
            "Failed to persist scan payload",
            extra={
                "output_dir": str(output_dir),
                "filename": filename,
                "bytes": len(data),
            },
        )
        return web.Response(status=500, text="Failed to save scan")

    log.info(
        "Scan saved",
        extra={
            "file": str(path),
            "bytes": len(data),
            "content_type": request.content_type,
            "detected_ext": ext,
        },
    )

    return web.Response(status=201, text="OK")

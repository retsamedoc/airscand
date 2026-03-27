"""Inbound scan receiver and persistence helpers."""

import logging
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


async def handle_scan(request: web.Request) -> web.Response:
    """Store uploaded scan payload to configured output directory."""
    data = await request.read()

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
        path.write_bytes(data)
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

    log.info("Scan saved", extra={"file": str(path)})

    return web.Response(text="OK")

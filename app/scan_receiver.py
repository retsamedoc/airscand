"""Inbound scan receiver and persistence helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

from app.config import Config
from app.scan_storage import detect_file_type, save_scan_file

__all__ = ["handle_scan", "detect_file_type"]

log = logging.getLogger(__name__)


async def handle_scan(request: web.Request) -> web.Response:
    """Store uploaded scan payload to configured output directory."""
    data = await request.read()
    if not data:
        log.warning(
            "Rejected empty scan payload",
            extra={"content_type": request.content_type, "content_length": request.content_length},
        )
        return web.Response(status=400, text="Empty scan payload")

    config = request.app.get("config")
    if not isinstance(config, Config):
        log.error("Scan request missing valid config object")
        return web.Response(status=500, text="Server configuration unavailable")
    output_dir = Path(getattr(config, "output_dir", "./scans"))

    try:
        save_scan_file(output_dir, data, content_type=request.content_type)
    except OSError:
        log.exception(
            "Failed to persist scan payload",
            extra={
                "output_dir": str(output_dir),
                "bytes": len(data),
            },
        )
        return web.Response(status=500, text="Failed to save")

    return web.Response(status=201, text="OK")

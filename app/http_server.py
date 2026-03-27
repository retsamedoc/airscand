"""HTTP server setup for WSD and scan upload endpoints."""

import asyncio
import logging

from aiohttp import web

from app.config import Config
from app.scan_receiver import handle_scan
from app.ws_scan import handle_wsd

log = logging.getLogger(__name__)


async def start_http_server(config: Config) -> None:
    """Start and keep alive the aiohttp server."""
    app = web.Application()
    app["config"] = config

    app.router.add_post(config.endpoint_path, handle_wsd)
    app.router.add_post(config.scan_path, handle_scan)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, config.host, config.port)
    await site.start()

    log.info("HTTP server started", extra={"port": config.port})

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        log.info("HTTP server cancellation received; shutting down")
        raise
    finally:
        await runner.cleanup()

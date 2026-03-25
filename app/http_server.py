from aiohttp import web
import asyncio
import logging
from app.ws_scan import handle_wsd
from app.scan_receiver import handle_scan

log = logging.getLogger(__name__)

async def start_http_server(config):
    app = web.Application()
    app["config"] = config

    app.router.add_post(config.endpoint_path, handle_wsd)
    app.router.add_post(config.scan_path, handle_scan)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, config.host, config.port)
    await site.start()

    log.info("HTTP server started", extra={"port": config.port})

    while True:
        await asyncio.sleep(3600)

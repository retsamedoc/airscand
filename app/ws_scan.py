import logging
from aiohttp import web

log = logging.getLogger(__name__)


async def handle_wsd(request: web.Request) -> web.Response:
    body = await request.read()
    log.info(
        "WSD SOAP request received",
        extra={"bytes": len(body), "content_type": request.content_type},
    )

    # Phase 0/2 behavior: accept and respond minimally so the service
    # can start and we can observe printer behavior in logs.
    return web.Response(text="OK", content_type="text/plain")


import logging
from aiohttp import web
from pathlib import Path
import uuid

log = logging.getLogger(__name__)

def detect_file_type(data: bytes):
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data.startswith(b"%PDF"):
        return "pdf"
    return "bin"

async def handle_scan(request):
    data = await request.read()

    ext = detect_file_type(data)
    filename = f"scan_{uuid.uuid4()}.{ext}"

    config = request.app.get("config")
    output_dir = Path(getattr(config, "output_dir", "./scans"))
    output_dir.mkdir(exist_ok=True)

    path = output_dir / filename
    path.write_bytes(data)

    log.info("Scan saved", extra={"file": str(path)})

    return web.Response(text="OK")

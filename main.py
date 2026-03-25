import asyncio
from app.config import Config
from app.logging import setup_logging
from app.discovery import start_discovery
from app.http_server import start_http_server

async def main():
    setup_logging()
    config = Config()

    await asyncio.gather(
        start_discovery(config),
        start_http_server(config),
    )

if __name__ == "__main__":
    asyncio.run(main())

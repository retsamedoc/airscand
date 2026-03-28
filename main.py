"""Service entrypoint for discovery, HTTP, and scanner registration."""

import asyncio
import logging
import uuid
from urllib.parse import urlsplit, urlunsplit

from app.config import Config
from app.discovery import discover_scanner_xaddr, start_discovery
from app.http_server import start_http_server
from app.logging import setup_logging
from app.ws_eventing_client import preflight_get_scanner_capabilities, register_with_scanner

__all__ = ["main"]

log = logging.getLogger(__name__)


def _resolve_subscribe_to_url(config: Config, scanner_xaddr: str) -> str:
    """Resolve WS-Eventing subscribe endpoint from config or scanner endpoint."""
    explicit = getattr(config, "scanner_subscribe_to_url", "") or ""
    if explicit.strip():
        return explicit.strip()

    parts = urlsplit(scanner_xaddr)
    base = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    return f"{base}/WDP/SCAN"


async def _eventing_registration_loop(config: Config) -> None:
    """Retry scanner eventing registration until a successful subscription."""
    backoff_sec = 2.0
    max_backoff_sec = 60.0
    notify_to = getattr(config, "eventing_notify_to_url", "") or (
        f"http://{config.advertise_addr}:{config.port}{config.endpoint_path}"
    )
    client_from_address = f"urn:uuid:{config.uuid}"

    while True:
        try:
            scanner_xaddr = await discover_scanner_xaddr(config)
            if not scanner_xaddr:
                log.info("Scanner endpoint not yet discovered; retrying registration")
            else:
                config.scanner_xaddr = scanner_xaddr
                preflight_details = None
                subscribe_to_url = _resolve_subscribe_to_url(config, scanner_xaddr)
                if getattr(config, "eventing_preflight_get", True):
                    preflight_details = await preflight_get_scanner_capabilities(
                        scanner_xaddr=scanner_xaddr,
                        get_to_url=subscribe_to_url,
                        from_address=client_from_address,
                    )
                    preflight_subscribe_to_url = preflight_details.get("suggested_subscribe_to_url")
                    if preflight_subscribe_to_url:
                        subscribe_to_url = preflight_subscribe_to_url
                log.debug(
                    "Scanner registration subscribe destination selected",
                    extra={
                        "scanner_xaddr": scanner_xaddr,
                        "subscribe_to_url": subscribe_to_url,
                        "preflight_message_id": (preflight_details or {}).get("message_id"),
                    },
                )
                subscription_identifier = f"urn:uuid:{uuid.uuid4()}"
                result = await register_with_scanner(
                    scanner_xaddr=scanner_xaddr,
                    subscribe_to_url=subscribe_to_url,
                    notify_to=notify_to,
                    from_address=client_from_address,
                    subscription_identifier=subscription_identifier,
                )
                status = int(result.get("status") or "0")
                if result.get("identifier") and (status == 0 or 200 <= status < 300):
                    sub_id = str(result.get("identifier") or "").strip()
                    setattr(config, "scanner_eventing_subscription_id", sub_id)
                    dest_tok = str(result.get("subscribe_destination_token") or "").strip()
                    setattr(config, "scanner_subscribe_destination_token", dest_tok)
                    raw_map = result.get("subscribe_destination_tokens")
                    if isinstance(raw_map, dict):
                        setattr(
                            config,
                            "scanner_subscribe_destination_tokens",
                            {str(k): str(v) for k, v in raw_map.items()},
                        )
                    else:
                        setattr(config, "scanner_subscribe_destination_tokens", {})
                    setattr(config, "use_env_subscribe_destination_token_only", False)
                    log.info(
                        "Scanner registration succeeded",
                        extra={
                            "scanner_xaddr": scanner_xaddr,
                            "subscribe_to_url": subscribe_to_url,
                            "subscription_id": result.get("identifier"),
                            "subscribe_destination_token": result.get("subscribe_destination_token"),
                            "subscribe_destination_tokens_count": len(
                                getattr(config, "scanner_subscribe_destination_tokens", {}) or {}
                            ),
                            "expires": result.get("expires"),
                        },
                    )
                    return
        except Exception:
            log.exception(
                "Scanner registration attempt failed",
                extra={
                    "notify_to": notify_to,
                    "client_from_address": client_from_address,
                    "backoff_sec": backoff_sec,
                },
            )

        await asyncio.sleep(backoff_sec)
        backoff_sec = min(backoff_sec * 2, max_backoff_sec)

async def main() -> None:
    """Initialize configuration and run all long-lived service tasks."""
    config = Config()
    setup_logging(config.log_level, log_json=config.log_json)

    await asyncio.gather(
        start_discovery(config),
        start_http_server(config),
        _eventing_registration_loop(config),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutdown requested; exiting")

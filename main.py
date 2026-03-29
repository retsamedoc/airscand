"""Service entrypoint for discovery, HTTP, and scanner registration."""

import asyncio
import logging
import signal
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

from app.config import Config
from app.discovery import discover_scanner_xaddr, start_discovery
from app.http_server import start_http_server
from app.logging import setup_logging
from app.ws_eventing_client import (
    SCANNER_STATUS_SUMMARY_EVENT_ACTION,
    parse_iso8601_duration_to_seconds,
    preflight_get_scanner_capabilities,
    register_with_scanner,
    renew_subscription,
    unsubscribe_from_scanner,
)

__all__ = ["main"]

log = logging.getLogger(__name__)


def _renew_delay_seconds(expires_raw: str, config: Config) -> float:
    """Seconds to wait before Renew: ``fraction * lease_duration`` from parsed ``Expires``."""
    fraction = config.eventing_renew_after_fraction
    fallback = config.eventing_renew_fallback_duration_sec
    trimmed = (expires_raw or "").strip()
    try:
        dur = parse_iso8601_duration_to_seconds(trimmed) if trimmed else fallback
    except ValueError:
        log.warning(
            "Unparsable WS-Eventing Expires %r; using fallback duration",
            expires_raw,
            extra={"fallback_sec": fallback},
        )
        dur = fallback
    if dur <= 0:
        dur = fallback
    return max(0.0, fraction * float(dur))


def _renew_result_ok(details: dict[str, str | None]) -> bool:
    """Return True when Renew returned HTTP success without SOAP fault."""
    if details.get("status") == "skipped":
        return False
    try:
        st = int(str(details.get("status") or "0"))
    except ValueError:
        return False
    if st != 0 and not (200 <= st < 300):
        return False
    return not bool(details.get("fault_code"))


async def _unsubscribe_eventing_best_effort(config: Config, client_from_address: str) -> None:
    """Best-effort Unsubscribe for ScannerStatusSummary then ScanAvailable subscriptions."""
    mgr = str(getattr(config, "scanner_eventing_subscribe_manager_url", "") or "").strip()
    mgr_ref = str(
        getattr(config, "scanner_eventing_subscribe_manager_reference_parameters_xml", "") or ""
    ).strip()
    mgr_status = str(
        getattr(config, "scanner_eventing_subscribe_manager_url_status", "") or ""
    ).strip()
    mgr_ref_status = str(
        getattr(config, "scanner_eventing_subscribe_manager_reference_parameters_xml_status", "")
        or ""
    ).strip()
    sub_id = str(getattr(config, "scanner_eventing_subscription_id", "") or "").strip()
    sub_id_status = str(
        getattr(config, "scanner_eventing_subscription_id_status", "") or ""
    ).strip()
    try:
        if sub_id_status:
            await unsubscribe_from_scanner(
                manager_url=mgr_status,
                subscription_id=sub_id_status,
                reference_parameters_xml=mgr_ref_status or None,
                from_address=client_from_address,
            )
        if sub_id:
            await unsubscribe_from_scanner(
                manager_url=mgr,
                subscription_id=sub_id,
                reference_parameters_xml=mgr_ref or None,
                from_address=client_from_address,
            )
    except Exception:
        log.exception("WS-Eventing best-effort unsubscribe failed")


async def _eventing_maintenance_loop(config: Config, *, client_from_address: str) -> None:
    """Sleep until lease fraction elapses, Renew each due subscription; exit on first Renew failure."""
    primary_next: float | None = None
    status_next: float | None = None

    def _recompute_deadlines() -> None:
        nonlocal primary_next, status_next
        exp_p = (getattr(config, "scanner_eventing_subscribe_expires", "") or "").strip()
        primary_next = time.monotonic() + _renew_delay_seconds(exp_p, config)
        if (getattr(config, "scanner_eventing_subscription_id_status", "") or "").strip():
            exp_s = (getattr(config, "scanner_eventing_subscribe_expires_status", "") or "").strip()
            status_next = time.monotonic() + _renew_delay_seconds(exp_s, config)
        else:
            status_next = None

    _recompute_deadlines()

    while True:
        candidates = [x for x in [primary_next, status_next] if x is not None]
        if not candidates:
            log.warning("Eventing maintenance has no renew deadlines; resubscribing")
            return
        wake_at = min(candidates)
        sleep_sec = max(0.0, wake_at - time.monotonic())
        if sleep_sec > 0:
            await asyncio.sleep(sleep_sec)

        now = time.monotonic()
        epsilon = 1e-3

        if primary_next is not None and primary_next <= now + epsilon:
            res = await renew_subscription(
                manager_url=config.scanner_eventing_subscribe_manager_url,
                subscription_id=config.scanner_eventing_subscription_id,
                reference_parameters_xml=config.scanner_eventing_subscribe_manager_reference_parameters_xml
                or None,
                from_address=client_from_address,
            )
            if not _renew_result_ok(res):
                log.warning(
                    "Primary WS-Eventing subscription renew failed; resubscribing",
                    extra={
                        "status": res.get("status"),
                        "fault_subcode": res.get("fault_subcode"),
                    },
                )
                await _unsubscribe_eventing_best_effort(config, client_from_address)
                return
            exp = (res.get("expires") or "").strip() or getattr(
                config, "scanner_eventing_subscribe_expires", ""
            )
            setattr(config, "scanner_eventing_subscribe_expires", str(exp).strip())
            primary_next = time.monotonic() + _renew_delay_seconds(
                getattr(config, "scanner_eventing_subscribe_expires", "") or "",
                config,
            )

        now = time.monotonic()
        if status_next is not None and status_next <= now + epsilon:
            res = await renew_subscription(
                manager_url=config.scanner_eventing_subscribe_manager_url_status,
                subscription_id=config.scanner_eventing_subscription_id_status,
                reference_parameters_xml=config.scanner_eventing_subscribe_manager_reference_parameters_xml_status
                or None,
                from_address=client_from_address,
            )
            if not _renew_result_ok(res):
                log.warning(
                    "ScannerStatusSummary WS-Eventing subscription renew failed; resubscribing",
                    extra={
                        "status": res.get("status"),
                        "fault_subcode": res.get("fault_subcode"),
                    },
                )
                await _unsubscribe_eventing_best_effort(config, client_from_address)
                return
            exp = (res.get("expires") or "").strip() or getattr(
                config, "scanner_eventing_subscribe_expires_status", ""
            )
            setattr(config, "scanner_eventing_subscribe_expires_status", str(exp).strip())
            status_next = time.monotonic() + _renew_delay_seconds(
                getattr(config, "scanner_eventing_subscribe_expires_status", "") or "",
                config,
            )


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
                    mgr_url = (result.get("subscription_manager_url") or "").strip()
                    mgr_ref = str(
                        result.get("subscription_manager_reference_parameters_xml") or ""
                    ).strip()
                    if not mgr_url:
                        log.warning(
                            "SubscribeResponse missing SubscriptionManager address; "
                            "outbound Unsubscribe will be skipped until resubscribe",
                            extra={
                                "scanner_xaddr": scanner_xaddr,
                                "subscribe_to_url": subscribe_to_url,
                            },
                        )
                    setattr(config, "scanner_eventing_subscribe_manager_url", mgr_url)
                    setattr(
                        config,
                        "scanner_eventing_subscribe_manager_reference_parameters_xml",
                        mgr_ref,
                    )
                    setattr(config, "scanner_eventing_subscription_id", sub_id)
                    setattr(
                        config,
                        "scanner_eventing_subscribe_expires",
                        str(result.get("expires") or "").strip(),
                    )
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
                    setattr(config, "scanner_eventing_subscription_id_status", "")
                    setattr(config, "scanner_eventing_subscribe_expires_status", "")
                    setattr(config, "scanner_eventing_subscribe_manager_url_status", "")
                    setattr(
                        config,
                        "scanner_eventing_subscribe_manager_reference_parameters_xml_status",
                        "",
                    )
                    status_sub_identifier = f"urn:uuid:{uuid.uuid4()}"
                    try:
                        status_result = await register_with_scanner(
                            scanner_xaddr=scanner_xaddr,
                            subscribe_to_url=subscribe_to_url,
                            notify_to=notify_to,
                            from_address=client_from_address,
                            subscription_identifier=status_sub_identifier,
                            filter_action=SCANNER_STATUS_SUMMARY_EVENT_ACTION,
                        )
                        st2 = int(status_result.get("status") or "0")
                        if status_result.get("identifier") and (st2 == 0 or 200 <= st2 < 300):
                            mgr_s = (status_result.get("subscription_manager_url") or "").strip()
                            mgr_ref_s = str(
                                status_result.get("subscription_manager_reference_parameters_xml")
                                or ""
                            ).strip()
                            if not mgr_s:
                                log.warning(
                                    "ScannerStatusSummary SubscribeResponse missing "
                                    "SubscriptionManager address; Unsubscribe for that subscription "
                                    "will be skipped",
                                    extra={"scanner_xaddr": scanner_xaddr},
                                )
                            setattr(
                                config,
                                "scanner_eventing_subscription_id_status",
                                str(status_result.get("identifier") or "").strip(),
                            )
                            setattr(config, "scanner_eventing_subscribe_manager_url_status", mgr_s)
                            setattr(
                                config,
                                "scanner_eventing_subscribe_manager_reference_parameters_xml_status",
                                mgr_ref_s,
                            )
                            setattr(
                                config,
                                "scanner_eventing_subscribe_expires_status",
                                str(status_result.get("expires") or "").strip(),
                            )
                            log.info(
                                "Scanner ScannerStatusSummaryEvent subscribe succeeded",
                                extra={
                                    "scanner_xaddr": scanner_xaddr,
                                    "subscription_id_status": status_result.get("identifier"),
                                },
                            )
                        else:
                            setattr(config, "scanner_eventing_subscribe_expires_status", "")
                            log.warning(
                                "Scanner ScannerStatusSummaryEvent subscribe missing id or non-success",
                                extra={
                                    "scanner_xaddr": scanner_xaddr,
                                    "status": status_result.get("status"),
                                    "fault_subcode": status_result.get("fault_subcode"),
                                },
                            )
                    except Exception:
                        log.exception(
                            "Scanner ScannerStatusSummaryEvent subscribe failed",
                            extra={"scanner_xaddr": scanner_xaddr},
                        )
                    log.info(
                        "Scanner registration succeeded",
                        extra={
                            "scanner_xaddr": scanner_xaddr,
                            "subscribe_to_url": subscribe_to_url,
                            "subscription_manager_url": mgr_url,
                            "subscription_id": result.get("identifier"),
                            "subscribe_destination_token": result.get(
                                "subscribe_destination_token"
                            ),
                            "subscribe_destination_tokens_count": len(
                                getattr(config, "scanner_subscribe_destination_tokens", {}) or {}
                            ),
                            "expires": result.get("expires"),
                            "subscription_id_status": getattr(
                                config, "scanner_eventing_subscription_id_status", ""
                            )
                            or None,
                        },
                    )
                    await _eventing_maintenance_loop(
                        config, client_from_address=client_from_address
                    )
                    log.info(
                        "Eventing lease maintenance ended; resubscribing",
                        extra={"scanner_xaddr": scanner_xaddr},
                    )
                    backoff_sec = 2.0
                    await asyncio.sleep(backoff_sec)
                    continue
        except asyncio.CancelledError:
            raise
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


async def _shutdown_services(
    config: Config,
    tasks: list[asyncio.Task[None]],
) -> None:
    """Unsubscribe from WS-Eventing, then cancel long-lived tasks (discovery sends Bye in ``finally``)."""
    client_from_address = f"urn:uuid:{config.uuid}"
    await _unsubscribe_eventing_best_effort(config, client_from_address)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def main() -> None:
    """Initialize configuration and run all long-lived service tasks."""
    config = Config()
    setup_logging(config.log_level, log_json=config.log_json)

    loop = asyncio.get_running_loop()
    tasks = [
        asyncio.create_task(start_discovery(config)),
        asyncio.create_task(start_http_server(config)),
        asyncio.create_task(_eventing_registration_loop(config)),
    ]
    shutdown_task: asyncio.Task[None] | None = None
    shutdown_started = False

    async def request_shutdown() -> None:
        nonlocal shutdown_started
        if shutdown_started:
            return
        shutdown_started = True
        log.info("Shutdown requested; cleaning up")
        await _shutdown_services(config, tasks)

    def on_signal() -> None:
        nonlocal shutdown_task
        if shutdown_task is not None and not shutdown_task.done():
            return
        shutdown_task = asyncio.create_task(request_shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, on_signal)
        except NotImplementedError:
            break

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, ValueError, RuntimeError):
                pass
        if shutdown_task is not None:
            await shutdown_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutdown requested; exiting")

"""WS-Scan SOAP parsing and response handlers."""

import asyncio
import logging
import uuid

from aiohttp import web

from app.inbound_eventing_registry import get_inbound_subscription_registry
from app.quirks import get_profile
from app.scanner_status_coordination import notify_scanner_state
from app.soap.addressing import extract_action, extract_message_id_optional, soap_action_short
from app.soap.builders.faults import build_wse_fault_body
from app.soap.envelope import build_inbound_fault_envelope, build_inbound_response_envelope
from app.soap.namespaces import (
    ACTION_WSA_FAULT,
    NS_SCA,
    NS_WSE,
    SCANNER_STATUS_SUMMARY_EVENT_ACTION,
    WSA_ANONYMOUS,
)
from app.soap.parsers.inbound_eventing import (
    PUSH_DELIVERY_MODE_URI,
    extract_management_subscription_identifier,
    extract_wsa_to_optional,
    grant_expires_from_request,
    parse_inbound_renew_expires_optional,
    parse_inbound_subscribe_body,
)
from app.ws_eventing_client import (
    parse_scanner_status_summary_event,
    run_scan_available_chain,
)

log = logging.getLogger(__name__)

ACTION_SUBSCRIBE = f"{NS_WSE}/Subscribe"
ACTION_RENEW = f"{NS_WSE}/Renew"
ACTION_GET_STATUS = f"{NS_WSE}/GetStatus"
ACTION_UNSUBSCRIBE = f"{NS_WSE}/Unsubscribe"
ACTION_CREATE_SCAN_JOB = f"{NS_SCA}/CreateScanJob"
ACTION_SCAN_AVAILABLE_EVENT = f"{NS_SCA}/ScanAvailableEvent"
ACTION_SUBSCRIBE_RESPONSE = f"{NS_WSE}/SubscribeResponse"
ACTION_RENEW_RESPONSE = f"{NS_WSE}/RenewResponse"
ACTION_GET_STATUS_RESPONSE = f"{NS_WSE}/GetStatusResponse"
ACTION_UNSUBSCRIBE_RESPONSE = f"{NS_WSE}/UnsubscribeResponse"
ACTION_CREATE_SCAN_JOB_RESPONSE = f"{NS_SCA}/CreateScanJobResponse"
# Not defined in Microsoft WS-Scan element docs; used only as wsa:Action for SOAP-shaped HTTP ack to the device.
ACTION_SCAN_AVAILABLE_EVENT_RESPONSE = f"{NS_SCA}/ScanAvailableEventResponse"
ACTION_SCANNER_STATUS_SUMMARY_EVENT_RESPONSE = f"{NS_SCA}/ScannerStatusSummaryEventResponse"


def _log_chain_result(task: asyncio.Task[dict[str, str | None]]) -> None:
    """Capture asynchronous chain completion and log failures."""
    try:
        result = task.result()
        log.info(
            "ScanAvailable follow-up chain completed",
            extra={
                "target_url": result.get("target_url"),
                "probe_http_status": result.get("probe_http_status"),
                "probe_fault_subcode": result.get("probe_fault_subcode"),
                "has_scanner_description": bool(result.get("scanner_description")),
                "has_default_scan_ticket": bool(result.get("default_scan_ticket")),
                "has_scanner_configuration": bool(result.get("scanner_configuration")),
                "has_scanner_status": bool(result.get("scanner_status")),
                "validate_http_status": result.get("validate_http_status"),
                "create_http_status": result.get("create_http_status"),
                "retrieve_http_status": result.get("retrieve_http_status"),
                "retrieve_status": result.get("retrieve_status"),
                "job_id": result.get("job_id"),
                "fault_subcode": result.get("fault_subcode"),
                "retrieve_fault_subcode": result.get("retrieve_fault_subcode"),
                "retrieve_elapsed_sec": result.get("retrieve_elapsed_sec"),
                "scanner_idle_wait_result": result.get("scanner_idle_wait_result"),
                "saved_scan_path": result.get("saved_scan_path"),
                "saved_scan_bytes": result.get("saved_scan_bytes"),
            },
        )
    except asyncio.CancelledError:
        log.info("ScanAvailable follow-up chain cancelled during shutdown")
    except Exception:
        log.exception("ScanAvailable follow-up chain failed")


def extract_message_id(text: str) -> str | None:
    """Extract WS-Addressing MessageID value from SOAP payload."""
    return extract_message_id_optional(text)


def _normalize_manager_addr(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _inbound_eventing_fault_response(
    relates_to: str | None,
    *,
    subcode_local: str,
    reason: str,
    log_action: str,
    log_extras: dict[str, object] | None = None,
) -> web.Response:
    """Return SOAP 1.2 fault (HTTP 200) for inbound WS-Eventing validation or lifecycle errors."""
    fault_body = build_wse_fault_body(subcode_local=subcode_local, reason=reason)
    xml = build_inbound_fault_envelope(relates_to=relates_to, fault_body_xml=fault_body)
    extra = {"http_status": 200, "bytes": len(xml.encode("utf-8")), "fault_subcode": subcode_local}
    if log_extras:
        extra.update(log_extras)
    log.info(
        f"{soap_action_short(log_action) or log_action}",
        extra={
            "soap_leg": "server_response",
            "soap_action": soap_action_short(log_action),
            **extra,
        },
    )
    return web.Response(
        text=xml,
        content_type="application/soap+xml",
        charset="utf-8",
        status=200,
    )


def _manager_to_matches_expected(to_hdr: str | None, manager_addr: str) -> bool:
    if not to_hdr or not to_hdr.strip():
        return True
    if to_hdr.strip() == WSA_ANONYMOUS:
        return True
    return _normalize_manager_addr(to_hdr) == _normalize_manager_addr(manager_addr)


def _max_inbound_eventing_grant_seconds(config: object) -> float:
    """Upper bound for granted ``wse:Expires`` on inbound Subscribe/Renew (default one day)."""
    raw = getattr(config, "inbound_eventing_max_grant_sec", None)
    if raw is None:
        return 86400.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 86400.0
    return v if v > 0 else 86400.0


def build_eventing_subscribe_response(
    relates_to: str | None, xaddr: str, identifier: str, expires: str
) -> str:
    """Build SOAP SubscribeResponse payload for WS-Eventing."""
    body = f"""    <wse:SubscribeResponse>
      <wse:SubscriptionManager>
        <wsa:Address>{xaddr}</wsa:Address>
        <wsman:Identifier>{identifier}</wsman:Identifier>
      </wse:SubscriptionManager>
      <wse:Expires>{expires}</wse:Expires>
    </wse:SubscribeResponse>"""
    return build_inbound_response_envelope(
        action=ACTION_SUBSCRIBE_RESPONSE, relates_to=relates_to, body_xml=body
    )


def build_eventing_renew_response(relates_to: str | None, expires: str) -> str:
    """Build SOAP RenewResponse payload."""
    body = f"    <wse:RenewResponse><wse:Expires>{expires}</wse:Expires></wse:RenewResponse>"
    return build_inbound_response_envelope(
        action=ACTION_RENEW_RESPONSE, relates_to=relates_to, body_xml=body
    )


def build_eventing_get_status_response(relates_to: str | None, expires: str) -> str:
    """Build SOAP GetStatusResponse payload."""
    body = (
        f"    <wse:GetStatusResponse><wse:Expires>{expires}</wse:Expires></wse:GetStatusResponse>"
    )
    return build_inbound_response_envelope(
        action=ACTION_GET_STATUS_RESPONSE, relates_to=relates_to, body_xml=body
    )


def build_eventing_unsubscribe_response(relates_to: str | None) -> str:
    """Build SOAP UnsubscribeResponse payload."""
    body = "    <wse:UnsubscribeResponse/>"
    return build_inbound_response_envelope(
        action=ACTION_UNSUBSCRIBE_RESPONSE, relates_to=relates_to, body_xml=body
    )


def build_scan_available_event_ack_response(relates_to: str | None) -> str:
    """Return a SOAP 1.2 envelope acknowledging ScanAvailableEvent delivery (sink HTTP response).

    Uses WS-Addressing headers with ``RelatesTo`` matching the notification ``wsa:MessageID`` and
    ``application/soap+xml`` content type, instead of a bare ``text/plain`` body.
    """
    return build_inbound_response_envelope(
        action=ACTION_SCAN_AVAILABLE_EVENT_RESPONSE,
        relates_to=relates_to,
        body_xml="",
    )


def build_scanner_status_summary_event_ack_response(relates_to: str | None) -> str:
    """Return a SOAP 1.2 envelope acknowledging ScannerStatusSummaryEvent delivery."""
    return build_inbound_response_envelope(
        action=ACTION_SCANNER_STATUS_SUMMARY_EVENT_RESPONSE,
        relates_to=relates_to,
        body_xml="",
    )


def build_create_scan_job_response(
    relates_to: str | None,
    job_id: str | None = None,
    job_token: str | None = None,
) -> str:
    """Build WS-Scan CreateScanJobResponse with required child elements."""
    resolved_job_id = job_id or str(uuid.uuid4())
    resolved_token = job_token or str(uuid.uuid4())
    body = f"""    <sca:CreateScanJobResponse>
      <sca:JobId>{resolved_job_id}</sca:JobId>
      <sca:JobToken>{resolved_token}</sca:JobToken>
      <sca:ImageInformation>
        <sca:Width>8500</sca:Width>
        <sca:Height>11700</sca:Height>
      </sca:ImageInformation>
      <sca:DocumentFinalParameters>
        <sca:Format>exif</sca:Format>
      </sca:DocumentFinalParameters>
    </sca:CreateScanJobResponse>"""
    return build_inbound_response_envelope(
        action=ACTION_CREATE_SCAN_JOB_RESPONSE,
        relates_to=relates_to,
        body_xml=body,
    )


async def handle_wsd(request: web.Request) -> web.Response:
    """Handle incoming WSD SOAP request and emit appropriate response."""
    body = await request.read()
    text = body.decode(errors="ignore")
    action = extract_action(text)
    relates_to = extract_message_id(text)
    config = request.app.get("config")
    xaddr = f"http://{config.advertise_addr}:{config.port}{config.endpoint_path}"

    log.info(
        f"{soap_action_short(action) or 'unknown'}",
        extra={
            "soap_leg": "server_request",
            "soap_action": soap_action_short(action),
            "wsa_message_id": relates_to,
            "bytes": len(body),
            "content_type": request.content_type,
        },
    )
    if not action:
        log.warning(
            "Invalid WSD SOAP request (missing Action)",
            extra={"bytes": len(body), "content_type": request.content_type},
        )

    if action == ACTION_SUBSCRIBE:
        if not relates_to:
            log.warning("Subscribe request missing MessageID")
        mgr = _normalize_manager_addr(xaddr)
        to_hdr = extract_wsa_to_optional(text)
        if not _manager_to_matches_expected(to_hdr, mgr):
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="InvalidMessage",
                reason="wsa:To does not match this subscription manager endpoint",
                log_action=ACTION_WSA_FAULT,
                log_extras={"wsa_to": to_hdr, "expected_manager": mgr},
            )
        parsed = parse_inbound_subscribe_body(text)
        if parsed is None:
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="InvalidMessage",
                reason="Invalid or missing wse:Subscribe body",
                log_action=ACTION_WSA_FAULT,
            )
        if parsed.has_filter:
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="FilteringNotSupported",
                reason="Event filtering is not supported by this endpoint",
                log_action=ACTION_WSA_FAULT,
            )
        mode = parsed.delivery_mode
        if not mode or mode.rstrip("/").lower() != PUSH_DELIVERY_MODE_URI.rstrip("/").lower():
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="DeliveryModeRequestedUnavailable",
                reason="Only Push delivery mode is supported",
                log_action=ACTION_WSA_FAULT,
                log_extras={"delivery_mode": mode},
            )
        if not parsed.notify_to_address:
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="InvalidMessage",
                reason="wse:NotifyTo/wsa:Address is required for Push delivery",
                log_action=ACTION_WSA_FAULT,
            )
        granted_str, grant_sec = grant_expires_from_request(
            parsed.requested_expires,
            max_seconds=_max_inbound_eventing_grant_seconds(config),
        )
        reg = get_inbound_subscription_registry()
        sub = reg.create(
            manager_address=mgr,
            granted_expires=granted_str,
            grant_seconds=grant_sec,
        )
        response_xml = build_eventing_subscribe_response(
            relates_to, xaddr, sub.identifier, sub.granted_expires
        )
        log.info(
            f"{soap_action_short(ACTION_SUBSCRIBE_RESPONSE) or 'SubscribeResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": soap_action_short(ACTION_SUBSCRIBE_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
                "subscription_id": sub.identifier,
            },
        )
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_RENEW:
        if not relates_to:
            log.warning("Renew request missing MessageID")
        mgr = _normalize_manager_addr(xaddr)
        to_hdr = extract_wsa_to_optional(text)
        if not _manager_to_matches_expected(to_hdr, mgr):
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="InvalidMessage",
                reason="wsa:To does not match this subscription manager endpoint",
                log_action=ACTION_WSA_FAULT,
                log_extras={"wsa_to": to_hdr, "expected_manager": mgr},
            )
        sub_id = extract_management_subscription_identifier(text)
        if not sub_id:
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="UnableToRenew",
                reason="Missing subscription identifier in SOAP header",
                log_action=ACTION_WSA_FAULT,
            )
        req_exp = parse_inbound_renew_expires_optional(text)
        granted_str, grant_sec = grant_expires_from_request(
            req_exp, max_seconds=_max_inbound_eventing_grant_seconds(config)
        )
        reg = get_inbound_subscription_registry()
        updated = reg.renew(
            identifier=sub_id,
            manager_address=mgr,
            granted_expires=granted_str,
            grant_seconds=grant_sec,
        )
        if updated is None:
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="UnableToRenew",
                reason="Unknown or expired subscription",
                log_action=ACTION_WSA_FAULT,
                log_extras={"subscription_id": sub_id},
            )
        response_xml = build_eventing_renew_response(relates_to, updated.granted_expires)
        log.info(
            f"{soap_action_short(ACTION_RENEW_RESPONSE) or 'RenewResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": soap_action_short(ACTION_RENEW_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
                "subscription_id": sub_id,
            },
        )
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_GET_STATUS:
        if not relates_to:
            log.warning("GetStatus request missing MessageID")
        mgr = _normalize_manager_addr(xaddr)
        to_hdr = extract_wsa_to_optional(text)
        if not _manager_to_matches_expected(to_hdr, mgr):
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="InvalidMessage",
                reason="wsa:To does not match this subscription manager endpoint",
                log_action=ACTION_WSA_FAULT,
                log_extras={"wsa_to": to_hdr, "expected_manager": mgr},
            )
        sub_id = extract_management_subscription_identifier(text)
        if not sub_id:
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="UnableToRenew",
                reason="Missing subscription identifier in SOAP header",
                log_action=ACTION_WSA_FAULT,
            )
        reg = get_inbound_subscription_registry()
        sub = reg.get_status(sub_id, mgr)
        if sub is None:
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="UnableToRenew",
                reason="Unknown or expired subscription",
                log_action=ACTION_WSA_FAULT,
                log_extras={"subscription_id": sub_id},
            )
        response_xml = build_eventing_get_status_response(relates_to, sub.granted_expires)
        log.info(
            f"{soap_action_short(ACTION_GET_STATUS_RESPONSE) or 'GetStatusResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": soap_action_short(ACTION_GET_STATUS_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
                "subscription_id": sub_id,
            },
        )
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_UNSUBSCRIBE:
        if not relates_to:
            log.warning("Unsubscribe request missing MessageID")
        mgr = _normalize_manager_addr(xaddr)
        to_hdr = extract_wsa_to_optional(text)
        if not _manager_to_matches_expected(to_hdr, mgr):
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="InvalidMessage",
                reason="wsa:To does not match this subscription manager endpoint",
                log_action=ACTION_WSA_FAULT,
                log_extras={"wsa_to": to_hdr, "expected_manager": mgr},
            )
        sub_id = extract_management_subscription_identifier(text)
        if not sub_id:
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="UnableToDestroySubscription",
                reason="Missing subscription identifier in SOAP header",
                log_action=ACTION_WSA_FAULT,
            )
        reg = get_inbound_subscription_registry()
        if not reg.unsubscribe(sub_id, mgr):
            return _inbound_eventing_fault_response(
                relates_to,
                subcode_local="UnableToDestroySubscription",
                reason="Unknown subscription or wrong subscription manager",
                log_action=ACTION_WSA_FAULT,
                log_extras={"subscription_id": sub_id},
            )
        response_xml = build_eventing_unsubscribe_response(relates_to)
        log.info(
            f"{soap_action_short(ACTION_UNSUBSCRIBE_RESPONSE) or 'UnsubscribeResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": soap_action_short(ACTION_UNSUBSCRIBE_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
                "subscription_id": sub_id,
            },
        )
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_CREATE_SCAN_JOB:
        if not relates_to:
            log.warning("CreateScanJob request missing MessageID")
        response_xml = build_create_scan_job_response(relates_to)
        log.info(
            f"{soap_action_short(ACTION_CREATE_SCAN_JOB_RESPONSE) or 'CreateScanJobResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": soap_action_short(ACTION_CREATE_SCAN_JOB_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
            },
        )
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == SCANNER_STATUS_SUMMARY_EVENT_ACTION:
        parsed = parse_scanner_status_summary_event(text)
        scanner_state = parsed.get("scanner_state")
        notify_scanner_state(scanner_state)
        ack_xml = build_scanner_status_summary_event_ack_response(relates_to)
        log.info(
            f"{soap_action_short(ACTION_SCANNER_STATUS_SUMMARY_EVENT_RESPONSE) or 'ScannerStatusSummaryEventResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": soap_action_short(ACTION_SCANNER_STATUS_SUMMARY_EVENT_RESPONSE),
                "http_status": 200,
                "bytes": len(ack_xml.encode("utf-8")),
                "scanner_state": scanner_state,
            },
        )
        return web.Response(
            text=ack_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_SCAN_AVAILABLE_EVENT:
        ack_xml = build_scan_available_event_ack_response(relates_to)
        scanner_xaddr = str(getattr(config, "scanner_xaddr", "") or "").strip()
        if not scanner_xaddr:
            log.warning("ScanAvailableEvent received but scanner_xaddr is not configured")
            log.info(
                f"{soap_action_short(ACTION_SCAN_AVAILABLE_EVENT_RESPONSE) or 'ScanAvailableEventResponse'}",
                extra={
                    "soap_leg": "server_response",
                    "soap_action": soap_action_short(ACTION_SCAN_AVAILABLE_EVENT_RESPONSE),
                    "http_status": 200,
                    "bytes": len(ack_xml.encode("utf-8")),
                },
            )
            return web.Response(
                text=ack_xml,
                content_type="application/soap+xml",
                charset="utf-8",
            )
        from_address = f"urn:uuid:{config.uuid}" if getattr(config, "uuid", "") else None
        subscription_id = str(getattr(config, "scanner_eventing_subscription_id", "") or "").strip()
        subscribe_dest = str(
            getattr(config, "scanner_subscribe_destination_token", "") or ""
        ).strip()
        dest_tokens_map = getattr(config, "scanner_subscribe_destination_tokens", None)
        if not isinstance(dest_tokens_map, dict):
            dest_tokens_map = {}
        use_env_dest_only = bool(getattr(config, "use_env_subscribe_destination_token_only", False))
        retry_invalid_dest = bool(
            getattr(config, "create_scan_job_retry_invalid_destination_token", True)
        )
        wait_idle = bool(getattr(config, "wait_scanner_idle_after_retrieve", True))
        idle_sec = float(getattr(config, "scanner_idle_wait_sec", 60.0))
        scanner_profile = get_profile(
            str(getattr(config, "scanner_profile", "") or "").strip() or "epson_wf_3640"
        )
        cfg_retrieve_timeout = getattr(config, "retrieve_image_timeout_sec", None)
        retrieve_timeout = (
            float(cfg_retrieve_timeout)
            if cfg_retrieve_timeout is not None
            else float(scanner_profile.retrieve_image_timeout_sec)
        )
        task = asyncio.create_task(
            run_scan_available_chain(
                scanner_xaddr=scanner_xaddr,
                scan_available_payload=text,
                retrieve_image_timeout_sec=retrieve_timeout,
                from_address=from_address,
                eventing_subscription_identifier=subscription_id or None,
                subscribe_destination_token=subscribe_dest or None,
                subscribe_destination_tokens=dest_tokens_map or None,
                use_env_subscribe_destination_token_only=use_env_dest_only,
                retry_create_without_destination_token_on_invalid_token=retry_invalid_dest,
                poll_get_job_status_before_retrieve=(
                    scanner_profile.poll_get_job_status_before_retrieve
                ),
                wait_scanner_idle_after_retrieve=wait_idle,
                scanner_idle_wait_sec=idle_sec,
                scanner_profile=scanner_profile,
                output_dir=getattr(config, "output_dir", None),
                scan_destinations=getattr(config, "scan_destinations", None),
            )
        )
        task.add_done_callback(_log_chain_result)
        log.info(
            f"{soap_action_short(ACTION_SCAN_AVAILABLE_EVENT_RESPONSE) or 'ScanAvailableEventResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": soap_action_short(ACTION_SCAN_AVAILABLE_EVENT_RESPONSE),
                "http_status": 200,
                "bytes": len(ack_xml.encode("utf-8")),
            },
        )
        log.info(
            "ScanAvailableEvent accepted; scheduled ValidateScanTicket/CreateScanJob chain",
            extra={"scanner_xaddr": scanner_xaddr, "message_id": relates_to},
        )
        return web.Response(
            text=ack_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )

    # Keep phase-2 bringup behavior for non-eventing actions while we
    # continue implementing broader WS-Scan SOAP surface.
    log.warning(
        "Unsupported WSD SOAP action; using plain OK fallback",
        extra={"action": action, "message_id": relates_to},
    )
    log.info(
        "OK",
        extra={
            "soap_leg": "server_response",
            "soap_action": "OK",
            "http_status": 200,
            "bytes": len("OK"),
        },
    )
    return web.Response(text="OK", content_type="text/plain")

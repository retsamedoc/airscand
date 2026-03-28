"""WS-Scan SOAP parsing and response handlers."""

import asyncio
import logging
import re
import uuid

from aiohttp import web

from app.ws_eventing_client import run_scan_available_chain

log = logging.getLogger(__name__)

NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
NS_WSE = "http://schemas.xmlsoap.org/ws/2004/08/eventing"
NS_WSMAN = "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
NS_SCA = "http://schemas.microsoft.com/windows/2006/08/wdp/scan"

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

ACTION_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Action>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Action>"
)
MESSAGE_ID_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?MessageID>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?MessageID>"
)


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
            },
        )
    except asyncio.CancelledError:
        log.info("ScanAvailable follow-up chain cancelled during shutdown")
    except Exception:
        log.exception("ScanAvailable follow-up chain failed")


def extract_action(text: str) -> str | None:
    """Extract WS-Addressing Action value from SOAP payload."""
    match = ACTION_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip()


def extract_message_id(text: str) -> str | None:
    """Extract WS-Addressing MessageID value from SOAP payload."""
    match = MESSAGE_ID_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _short_soap_action(action: str | None) -> str | None:
    """Last path segment of a SOAP Action URI for compact logs."""
    if not action:
        return None
    return action.rstrip("/").rsplit("/", 1)[-1]


def _new_message_id() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def _soap_response(
    *,
    action: str,
    relates_to: str | None,
    body_xml: str = "",
    outbound_message_id: str | None = None,
) -> str:
    mid = outbound_message_id or _new_message_id()
    relates_line = f"    <wsa:RelatesTo>{relates_to}</wsa:RelatesTo>\n" if relates_to else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:wse="{NS_WSE}" xmlns:wsman="{NS_WSMAN}" xmlns:sca="{NS_SCA}">
  <soap:Header>
    <wsa:Action>{action}</wsa:Action>
    <wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
{relates_line}  </soap:Header>
  <soap:Body>
{body_xml}
  </soap:Body>
</soap:Envelope>
"""


def build_eventing_subscribe_response(relates_to: str | None, xaddr: str) -> str:
    """Build SOAP SubscribeResponse payload for WS-Eventing."""
    body = f"""    <wse:SubscribeResponse>
      <wse:SubscriptionManager>
        <wsa:Address>{xaddr}</wsa:Address>
        <wsman:Identifier>{uuid.uuid4()}</wsman:Identifier>
      </wse:SubscriptionManager>
      <wse:Expires>PT1H</wse:Expires>
    </wse:SubscribeResponse>"""
    return _soap_response(action=ACTION_SUBSCRIBE_RESPONSE, relates_to=relates_to, body_xml=body)


def build_eventing_renew_response(relates_to: str | None) -> str:
    """Build SOAP RenewResponse payload."""
    body = "    <wse:RenewResponse><wse:Expires>PT1H</wse:Expires></wse:RenewResponse>"
    return _soap_response(action=ACTION_RENEW_RESPONSE, relates_to=relates_to, body_xml=body)


def build_eventing_get_status_response(relates_to: str | None) -> str:
    """Build SOAP GetStatusResponse payload."""
    body = "    <wse:GetStatusResponse><wse:Expires>PT1H</wse:Expires></wse:GetStatusResponse>"
    return _soap_response(action=ACTION_GET_STATUS_RESPONSE, relates_to=relates_to, body_xml=body)


def build_eventing_unsubscribe_response(relates_to: str | None) -> str:
    """Build SOAP UnsubscribeResponse payload."""
    body = "    <wse:UnsubscribeResponse/>"
    return _soap_response(action=ACTION_UNSUBSCRIBE_RESPONSE, relates_to=relates_to, body_xml=body)


def build_scan_available_event_ack_response(relates_to: str | None) -> str:
    """Return a SOAP 1.2 envelope acknowledging ScanAvailableEvent delivery (sink HTTP response).

    Uses WS-Addressing headers with ``RelatesTo`` matching the notification ``wsa:MessageID`` and
    ``application/soap+xml`` content type, instead of a bare ``text/plain`` body.
    """
    return _soap_response(
        action=ACTION_SCAN_AVAILABLE_EVENT_RESPONSE,
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
    return _soap_response(
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
        f"{_short_soap_action(action) or 'unknown'}",
        extra={
            "soap_leg": "server_request",
            "soap_action": _short_soap_action(action),
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
        response_xml = build_eventing_subscribe_response(relates_to, xaddr)
        log.info(
            f"{_short_soap_action(ACTION_SUBSCRIBE_RESPONSE) or 'SubscribeResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": _short_soap_action(ACTION_SUBSCRIBE_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
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
        response_xml = build_eventing_renew_response(relates_to)
        log.info(
            f"{_short_soap_action(ACTION_RENEW_RESPONSE) or 'RenewResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": _short_soap_action(ACTION_RENEW_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
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
        response_xml = build_eventing_get_status_response(relates_to)
        log.info(
            f"{_short_soap_action(ACTION_GET_STATUS_RESPONSE) or 'GetStatusResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": _short_soap_action(ACTION_GET_STATUS_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
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
        response_xml = build_eventing_unsubscribe_response(relates_to)
        log.info(
            f"{_short_soap_action(ACTION_UNSUBSCRIBE_RESPONSE) or 'UnsubscribeResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": _short_soap_action(ACTION_UNSUBSCRIBE_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
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
            f"{_short_soap_action(ACTION_CREATE_SCAN_JOB_RESPONSE) or 'CreateScanJobResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": _short_soap_action(ACTION_CREATE_SCAN_JOB_RESPONSE),
                "http_status": 200,
                "bytes": len(response_xml.encode("utf-8")),
            },
        )
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_SCAN_AVAILABLE_EVENT:
        ack_xml = build_scan_available_event_ack_response(relates_to)
        scanner_xaddr = str(getattr(config, "scanner_xaddr", "") or "").strip()
        if not scanner_xaddr:
            log.warning("ScanAvailableEvent received but scanner_xaddr is not configured")
            log.info(
                f"{_short_soap_action(ACTION_SCAN_AVAILABLE_EVENT_RESPONSE) or 'ScanAvailableEventResponse'}",
                extra={
                    "soap_leg": "server_response",
                    "soap_action": _short_soap_action(ACTION_SCAN_AVAILABLE_EVENT_RESPONSE),
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
        subscription_id = str(
            getattr(config, "scanner_eventing_subscription_id", "") or ""
        ).strip()
        subscribe_dest = str(
            getattr(config, "scanner_subscribe_destination_token", "") or ""
        ).strip()
        dest_tokens_map = getattr(config, "scanner_subscribe_destination_tokens", None)
        if not isinstance(dest_tokens_map, dict):
            dest_tokens_map = {}
        use_env_dest_only = bool(
            getattr(config, "use_env_subscribe_destination_token_only", False)
        )
        retry_invalid_dest = bool(
            getattr(config, "create_scan_job_retry_invalid_destination_token", True)
        )
        task = asyncio.create_task(
            run_scan_available_chain(
                scanner_xaddr=scanner_xaddr,
                scan_available_payload=text,
                from_address=from_address,
                eventing_subscription_identifier=subscription_id or None,
                subscribe_destination_token=subscribe_dest or None,
                subscribe_destination_tokens=dest_tokens_map or None,
                use_env_subscribe_destination_token_only=use_env_dest_only,
                retry_create_without_destination_token_on_invalid_token=retry_invalid_dest,
            )
        )
        task.add_done_callback(_log_chain_result)
        log.info(
            f"{_short_soap_action(ACTION_SCAN_AVAILABLE_EVENT_RESPONSE) or 'ScanAvailableEventResponse'}",
            extra={
                "soap_leg": "server_response",
                "soap_action": _short_soap_action(ACTION_SCAN_AVAILABLE_EVENT_RESPONSE),
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


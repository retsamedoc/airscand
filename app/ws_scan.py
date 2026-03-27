"""WS-Scan SOAP parsing and response handlers."""

import logging
import re
import uuid

from aiohttp import web

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
ACTION_SUBSCRIBE_RESPONSE = f"{NS_WSE}/SubscribeResponse"
ACTION_RENEW_RESPONSE = f"{NS_WSE}/RenewResponse"
ACTION_GET_STATUS_RESPONSE = f"{NS_WSE}/GetStatusResponse"
ACTION_UNSUBSCRIBE_RESPONSE = f"{NS_WSE}/UnsubscribeResponse"
ACTION_CREATE_SCAN_JOB_RESPONSE = f"{NS_SCA}/CreateScanJobResponse"

ACTION_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Action>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Action>"
)
MESSAGE_ID_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?MessageID>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?MessageID>"
)


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


def build_create_scan_job_response(relates_to: str | None, job_id: str | None = None) -> str:
    """Build minimal WS-Scan CreateScanJobResponse payload."""
    resolved_job_id = job_id or str(uuid.uuid4())
    body = f"""    <sca:CreateScanJobResponse>
      <sca:JobId>{resolved_job_id}</sca:JobId>
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
        "WSD SOAP request received",
        extra={
            "bytes": len(body),
            "content_type": request.content_type,
            "action": action,
            "message_id": relates_to,
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
        log.info("WSD SOAP response sent", extra={"response_action": ACTION_SUBSCRIBE_RESPONSE})
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_RENEW:
        if not relates_to:
            log.warning("Renew request missing MessageID")
        response_xml = build_eventing_renew_response(relates_to)
        log.info("WSD SOAP response sent", extra={"response_action": ACTION_RENEW_RESPONSE})
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_GET_STATUS:
        if not relates_to:
            log.warning("GetStatus request missing MessageID")
        response_xml = build_eventing_get_status_response(relates_to)
        log.info("WSD SOAP response sent", extra={"response_action": ACTION_GET_STATUS_RESPONSE})
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )
    if action == ACTION_UNSUBSCRIBE:
        if not relates_to:
            log.warning("Unsubscribe request missing MessageID")
        response_xml = build_eventing_unsubscribe_response(relates_to)
        log.info("WSD SOAP response sent", extra={"response_action": ACTION_UNSUBSCRIBE_RESPONSE})
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
            "WSD SOAP response sent",
            extra={"response_action": ACTION_CREATE_SCAN_JOB_RESPONSE},
        )
        return web.Response(
            text=response_xml,
            content_type="application/soap+xml",
            charset="utf-8",
        )

    # Keep phase-2 bringup behavior for non-eventing actions while we
    # continue implementing broader WS-Scan SOAP surface.
    log.warning(
        "Unsupported WSD SOAP action; using plain OK fallback",
        extra={"action": action, "message_id": relates_to},
    )
    return web.Response(text="OK", content_type="text/plain")


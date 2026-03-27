import logging
import re
import uuid
import asyncio

from aiohttp import ClientError, ClientSession

NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
NS_WSE = "http://schemas.xmlsoap.org/ws/2004/08/eventing"
NS_SCA = "http://schemas.microsoft.com/windows/2006/08/wdp/scan"
NS_WSMAN = "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
NS_WST = "http://schemas.xmlsoap.org/ws/2004/09/transfer"
FILTER_DIALECT_DEVPROF_ACTION = "http://schemas.xmlsoap.org/ws/2006/02/devprof/Action"
SCAN_AVAILABLE_EVENT_ACTION = f"{NS_SCA}/ScanAvailableEvent"

ACTION_SUBSCRIBE = f"{NS_WSE}/Subscribe"
ACTION_GET = f"{NS_WST}/Get"
WSA_ANONYMOUS = f"{NS_WSA}/role/anonymous"
DEFAULT_SCAN_DESTINATIONS = (
    ("Scan to airscand", "Scan"),
    ("Scan for Print to airscand", "ScanToPrint"),
    ("Scan for E-mail to airscand", "ScanToEmail"),
    ("Scan for Fax to airscand", "ScanToFax"),
    ("Scan for OCR to airscand", "ScanToOCR"),
)

IDENTIFIER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Identifier>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Identifier>"
)
EXPIRES_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Expires>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?Expires>"
)
FAULT_CODE_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Code>.*?<soap:Value>\s*([^<\s]+)\s*</soap:Value>",
    re.DOTALL,
)
FAULT_SUBCODE_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Subcode>.*?<soap:Value>\s*([^<\s]+)\s*</soap:Value>",
    re.DOTALL,
)
FAULT_REASON_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Reason>.*?<soap:Text[^>]*>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?Text>",
    re.DOTALL,
)
URI_TEXT_PATTERN = re.compile(r"https?://[A-Za-z0-9._:/-]+")

log = logging.getLogger(__name__)


def _new_message_id() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def build_subscribe_request(
    *,
    notify_to: str,
    to_url: str,
    from_address: str | None = None,
    subscription_identifier: str | None = None,
    filter_action: str = SCAN_AVAILABLE_EVENT_ACTION,
    scan_destinations: tuple[tuple[str, str], ...] = DEFAULT_SCAN_DESTINATIONS,
    message_id: str | None = None,
) -> tuple[str, str]:
    mid = message_id or _new_message_id()
    from_line = f"""    <wsa:From>
      <wsa:Address>{from_address}</wsa:Address>
    </wsa:From>
""" if from_address else ""
    subscription_identifier = subscription_identifier or _new_message_id()
    ref_params = f"""          <wsa:ReferenceParameters>
            <wse:Identifier>{subscription_identifier}</wse:Identifier>
          </wsa:ReferenceParameters>
"""
    destinations_xml = "".join(
        f"""        <sca:ScanDestination>
          <sca:ClientDisplayName>{display_name}</sca:ClientDisplayName>
          <sca:ClientContext>{client_context}</sca:ClientContext>
        </sca:ScanDestination>
"""
        for display_name, client_context in scan_destinations
    )

    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:wse="{NS_WSE}" xmlns:sca="{NS_SCA}">
  <soap:Header>
    <wsa:Action>{ACTION_SUBSCRIBE}</wsa:Action>
    <wsa:To>{to_url}</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
{from_line}    <wsa:ReplyTo>
      <wsa:Address>{WSA_ANONYMOUS}</wsa:Address>
    </wsa:ReplyTo>
  </soap:Header>
  <soap:Body>
    <wse:Subscribe>
      <wse:EndTo>
        <wsa:Address>{notify_to}</wsa:Address>
{ref_params}      </wse:EndTo>
      <wse:Delivery Mode="http://schemas.xmlsoap.org/ws/2004/08/eventing/DeliveryModes/Push">
        <wse:NotifyTo>
          <wsa:Address>{notify_to}</wsa:Address>
{ref_params}        </wse:NotifyTo>
      </wse:Delivery>
      <wse:Filter Dialect="{FILTER_DIALECT_DEVPROF_ACTION}">{filter_action}</wse:Filter>
      <sca:ScanDestinations>
{destinations_xml}      </sca:ScanDestinations>
      <wse:Expires>PT1H</wse:Expires>
    </wse:Subscribe>
  </soap:Body>
</soap:Envelope>
"""
    return mid, body


def build_get_request(
    *,
    to_url: str,
    message_id: str | None = None,
    from_address: str | None = None,
) -> tuple[str, str]:
    mid = message_id or _new_message_id()
    from_line = f"""    <wsa:From>
      <wsa:Address>{from_address}</wsa:Address>
    </wsa:From>
""" if from_address else ""
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:wst="{NS_WST}">
  <soap:Header>
    <wsa:Action>{ACTION_GET}</wsa:Action>
    <wsa:To>{to_url}</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
{from_line}    <wsa:ReplyTo>
      <wsa:Address>{WSA_ANONYMOUS}</wsa:Address>
    </wsa:ReplyTo>
  </soap:Header>
  <soap:Body/>
</soap:Envelope>
"""
    return mid, body


def parse_subscribe_response(text: str) -> dict[str, str | None]:
    identifier_match = IDENTIFIER_PATTERN.search(text)
    expires_match = EXPIRES_PATTERN.search(text)
    return {
        "identifier": identifier_match.group(1).strip() if identifier_match else None,
        "expires": expires_match.group(1).strip() if expires_match else None,
    }


def parse_get_response(text: str) -> dict[str, str | None]:
    values = URI_TEXT_PATTERN.findall(text)
    subscribe_to = next((value for value in values if "/WDP/SCAN" in value), None)
    if not subscribe_to:
        subscribe_to = next((value for value in values if "WSDScanner" in value), None)
    return {"suggested_subscribe_to_url": subscribe_to}


def parse_soap_fault(text: str) -> dict[str, str | None]:
    code_match = FAULT_CODE_PATTERN.search(text)
    subcode_match = FAULT_SUBCODE_PATTERN.search(text)
    reason_match = FAULT_REASON_PATTERN.search(text)
    return {
        "fault_code": code_match.group(1).strip() if code_match else None,
        "fault_subcode": subcode_match.group(1).strip() if subcode_match else None,
        "fault_reason": reason_match.group(1).strip() if reason_match else None,
    }


async def _post_soap(
    *,
    url: str,
    payload: str,
    timeout_sec: float,
) -> tuple[int, str]:
    headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
    async with ClientSession() as session:
        async with session.post(
            url,
            data=payload.encode("utf-8"),
            headers=headers,
            timeout=timeout_sec,
        ) as response:
            return response.status, await response.text()


async def preflight_get_scanner_capabilities(
    *,
    scanner_xaddr: str,
    timeout_sec: float = 5.0,
    get_to_url: str | None = None,
    from_address: str | None = None,
):
    get_url = get_to_url or scanner_xaddr
    message_id, payload = build_get_request(to_url=get_url, from_address=from_address)
    log.info(
        "Outbound WS-Transfer Get sending",
        extra={
            "scanner_xaddr": scanner_xaddr,
            "get_to_url": get_url,
            "get_message_id": message_id,
            "timeout_sec": timeout_sec,
        },
    )
    try:
        status, response_text = await _post_soap(
            url=get_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        details = parse_get_response(response_text)
        details.update(parse_soap_fault(response_text))
        details.update({"status": str(status), "message_id": message_id})
        if status < 200 or status >= 300:
            log.warning(
                "Outbound WS-Transfer Get returned non-success status",
                extra={
                    "scanner_xaddr": scanner_xaddr,
                    "get_to_url": get_url,
                    "status": status,
                    "fault_subcode": details["fault_subcode"],
                    "fault_reason": details["fault_reason"],
                },
            )
        log.info(
            "Outbound WS-Transfer Get completed",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "get_to_url": get_url,
                "status": status,
                "get_message_id": message_id,
                "suggested_subscribe_to_url": details["suggested_subscribe_to_url"],
            },
        )
        return details
    except asyncio.TimeoutError:
        log.warning(
            "Outbound WS-Transfer Get timed out",
            extra={"scanner_xaddr": scanner_xaddr, "get_to_url": get_url, "timeout_sec": timeout_sec},
        )
        raise
    except ClientError as exc:
        log.warning(
            "Outbound WS-Transfer Get transport error",
            extra={"scanner_xaddr": scanner_xaddr, "get_to_url": get_url, "error": str(exc)},
        )
        raise


async def register_with_scanner(
    *,
    scanner_xaddr: str,
    notify_to: str,
    timeout_sec: float = 5.0,
    subscribe_to_url: str | None = None,
    from_address: str | None = None,
    subscription_identifier: str | None = None,
    filter_action: str = SCAN_AVAILABLE_EVENT_ACTION,
    scan_destinations: tuple[tuple[str, str], ...] = DEFAULT_SCAN_DESTINATIONS,
):
    to_url = subscribe_to_url or scanner_xaddr
    message_id, payload = build_subscribe_request(
        notify_to=notify_to,
        to_url=to_url,
        from_address=from_address,
        subscription_identifier=subscription_identifier,
        filter_action=filter_action,
        scan_destinations=scan_destinations,
    )
    log.info(
        "Outbound WS-Eventing subscribe sending",
        extra={
            "scanner_xaddr": scanner_xaddr,
            "subscribe_to_url": to_url,
            "notify_to": notify_to,
            "message_id": message_id,
            "timeout_sec": timeout_sec,
        },
    )

    try:
        status, response_text = await _post_soap(
            url=to_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        details = parse_subscribe_response(response_text)
        details.update(parse_soap_fault(response_text))
        details.update({"status": str(status), "message_id": message_id})
        if status < 200 or status >= 300:
            log.warning(
                "Outbound WS-Eventing subscribe returned non-success status",
                extra={
                    "scanner_xaddr": scanner_xaddr,
                    "subscribe_to_url": to_url,
                    "status": status,
                    "fault_subcode": details["fault_subcode"],
                    "fault_reason": details["fault_reason"],
                },
            )
        if not details["identifier"]:
            log.warning(
                "Outbound WS-Eventing subscribe response missing Identifier",
                extra={
                    "scanner_xaddr": scanner_xaddr,
                    "subscribe_to_url": to_url,
                    "status": status,
                },
            )
        log.info(
            "Outbound WS-Eventing subscribe completed",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "subscribe_to_url": to_url,
                "notify_to": notify_to,
                "status": status,
                "subscription_id": details["identifier"],
                "expires": details["expires"],
                "fault_subcode": details["fault_subcode"],
                "subscribe_message_id": message_id,
            },
        )
        return details
    except asyncio.TimeoutError:
        log.warning(
            "Outbound WS-Eventing subscribe timed out",
            extra={"scanner_xaddr": scanner_xaddr, "timeout_sec": timeout_sec},
        )
        raise
    except ClientError as exc:
        log.warning(
            "Outbound WS-Eventing subscribe transport error",
            extra={"scanner_xaddr": scanner_xaddr, "error": str(exc)},
        )
        raise

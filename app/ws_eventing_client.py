"""Outbound WS-Eventing and WS-Transfer client helpers."""

import asyncio
import logging
import re
import time
import uuid

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
ACTION_VALIDATE_SCAN_TICKET = f"{NS_SCA}/ValidateScanTicket"
ACTION_CREATE_SCAN_JOB = f"{NS_SCA}/CreateScanJob"
ACTION_RETRIEVE_IMAGE = f"{NS_SCA}/RetrieveImage"
ACTION_GET_SCANNER_ELEMENTS = f"{NS_SCA}/GetScannerElements"
WSA_ANONYMOUS = f"{NS_WSA}/role/anonymous"
DEFAULT_DOCUMENT_DESCRIPTION = "1"
INVALID_DESTINATION_TOKEN_FAULT = "ClientErrorInvalidDestinationToken"
# SOAP text for GetScannerElements must be QName values (namespace prefix + local name).
# See Microsoft "Name for RequestedElements element" WS-Scan reference.
SCANNER_METADATA_ELEMENT_PREFIX = "sca"
SCANNER_METADATA_ELEMENT_NAMES = (
    f"{SCANNER_METADATA_ELEMENT_PREFIX}:ScannerDescription",
    f"{SCANNER_METADATA_ELEMENT_PREFIX}:DefaultScanTicket",
    f"{SCANNER_METADATA_ELEMENT_PREFIX}:ScannerConfiguration",
    f"{SCANNER_METADATA_ELEMENT_PREFIX}:ScannerStatus",
)
SCANNER_METADATA_ELEMENT_NAMES_NO_DEFAULT_TICKET = (
    f"{SCANNER_METADATA_ELEMENT_PREFIX}:ScannerDescription",
    f"{SCANNER_METADATA_ELEMENT_PREFIX}:ScannerConfiguration",
    f"{SCANNER_METADATA_ELEMENT_PREFIX}:ScannerStatus",
)
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
JOB_ID_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?JobId>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?JobId>"
)
JOB_TOKEN_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?JobToken>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?JobToken>"
)
VALIDATE_STATUS_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ValidateScanTicketResponse[^>]*>.*?<"
    r"(?:[A-Za-z0-9_]+:)?Status>\s*([^<]+)\s*</(?:[A-Za-z0-9_]+:)?Status>",
    re.DOTALL,
)
VALID_TICKET_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ValidTicket>\s*(true|false)\s*</(?:[A-Za-z0-9_]+:)?ValidTicket>",
    re.IGNORECASE,
)
STATUS_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Status>\s*([^<]+)\s*</(?:[A-Za-z0-9_]+:)?Status>"
)
DESTINATION_TOKEN_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?DestinationToken>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?DestinationToken>"
)
# SubscribeResponse may include wscn:DestinationResponses / DestinationResponse / DestinationToken (WS-Scan).
DESTINATION_RESPONSES_BLOCK_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?DestinationResponses\b[^>]*>.*?</(?:[A-Za-z0-9_]+:)?DestinationResponses>",
    re.DOTALL | re.IGNORECASE,
)
DESTINATION_RESPONSE_BLOCK_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?DestinationResponse\b[^>]*>.*?</(?:[A-Za-z0-9_]+:)?DestinationResponse>",
    re.DOTALL | re.IGNORECASE,
)
CLIENT_CONTEXT_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ClientContext>\s*([^<]*?)\s*</(?:[A-Za-z0-9_]+:)?ClientContext>",
    re.DOTALL,
)
SCAN_IDENTIFIER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ScanIdentifier>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?ScanIdentifier>"
)
# First match: typical SOAP places wsa:MessageID in Header before Body (scanner outbound response).
WSA_MESSAGE_ID_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?MessageID>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?MessageID>"
)
WSA_ACTION_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Action>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Action>"
)


def _extract_wsa_action(payload: str) -> str | None:
    """Return first WS-Addressing Action URI in a SOAP envelope."""
    match = WSA_ACTION_PATTERN.search(payload)
    return match.group(1).strip() if match else None


def _soap_action_short(action: str | None) -> str | None:
    """Last path segment of a SOAP Action URI for compact logs."""
    if not action:
        return None
    return action.rstrip("/").rsplit("/", 1)[-1]

SCAN_TICKET_TEMPLATE_XML = """      <sca:ScanTicket>
        <sca:JobDescription>
          <sca:JobName>Validating scan ticket for current WIA item properties</sca:JobName>
          <sca:JobOriginatingUserName>WIA session run for WIN10VM\\retsamedoc on WIN10VM</sca:JobOriginatingUserName>
          <sca:JobInformation>Scanning from platen..</sca:JobInformation>
        </sca:JobDescription>
        <sca:DocumentParameters>
          <sca:Format sca:MustHonor="true">exif</sca:Format>
          <sca:ImagesToTransfer sca:MustHonor="true">1</sca:ImagesToTransfer>
          <sca:InputSource sca:MustHonor="true">Platen</sca:InputSource>
          <sca:InputSize sca:MustHonor="true">
            <sca:InputMediaSize>
              <sca:Width>8500</sca:Width>
              <sca:Height>11700</sca:Height>
            </sca:InputMediaSize>
          </sca:InputSize>
          <sca:Exposure sca:MustHonor="true">
            <sca:ExposureSettings>
              <sca:Contrast>0</sca:Contrast>
              <sca:Brightness>0</sca:Brightness>
            </sca:ExposureSettings>
          </sca:Exposure>
          <sca:Scaling sca:MustHonor="true">
            <sca:ScalingWidth>100</sca:ScalingWidth>
            <sca:ScalingHeight>100</sca:ScalingHeight>
          </sca:Scaling>
          <sca:Rotation sca:MustHonor="true">0</sca:Rotation>
          <sca:MediaSides>
            <sca:MediaFront>
              <sca:ScanRegion>
                <sca:ScanRegionXOffset sca:MustHonor="true">0</sca:ScanRegionXOffset>
                <sca:ScanRegionYOffset sca:MustHonor="true">0</sca:ScanRegionYOffset>
                <sca:ScanRegionWidth>8500</sca:ScanRegionWidth>
                <sca:ScanRegionHeight>11700</sca:ScanRegionHeight>
              </sca:ScanRegion>
              <sca:ColorProcessing sca:MustHonor="true">RGB24</sca:ColorProcessing>
              <sca:Resolution sca:MustHonor="true">
                <sca:Width>300</sca:Width>
                <sca:Height>300</sca:Height>
              </sca:Resolution>
            </sca:MediaFront>
          </sca:MediaSides>
        </sca:DocumentParameters>
      </sca:ScanTicket>"""

log = logging.getLogger(__name__)


def _new_message_id() -> str:
    """Generate WS-Addressing message identifier."""
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
    """Build WS-Eventing Subscribe SOAP envelope."""
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
    """Build WS-Transfer Get SOAP envelope."""
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


def build_validate_scan_ticket_request(
    *,
    to_url: str,
    message_id: str | None = None,
    from_address: str | None = None,
    scan_ticket_xml: str | None = None,
) -> tuple[str, str]:
    """Build WS-Scan ValidateScanTicket SOAP envelope."""
    mid = message_id or _new_message_id()
    ticket_block = scan_ticket_xml if scan_ticket_xml is not None else SCAN_TICKET_TEMPLATE_XML
    from_line = f"""    <wsa:From>
      <wsa:Address>{from_address}</wsa:Address>
    </wsa:From>
""" if from_address else ""
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:sca="{NS_SCA}">
  <soap:Header>
    <wsa:Action>{ACTION_VALIDATE_SCAN_TICKET}</wsa:Action>
    <wsa:To>{to_url}</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
{from_line}    <wsa:ReplyTo>
      <wsa:Address>{WSA_ANONYMOUS}</wsa:Address>
    </wsa:ReplyTo>
  </soap:Header>
  <soap:Body>
    <sca:ValidateScanTicketRequest>
{ticket_block}
    </sca:ValidateScanTicketRequest>
  </soap:Body>
</soap:Envelope>
"""
    return mid, body


def build_create_scan_job_request(
    *,
    to_url: str,
    destination_token: str | None = None,
    scan_identifier: str | None = None,
    message_id: str | None = None,
    from_address: str | None = None,
    scan_ticket_xml: str | None = None,
) -> tuple[str, str]:
    """Build minimal WS-Scan CreateScanJob SOAP envelope."""
    mid = message_id or _new_message_id()
    ticket_block = scan_ticket_xml if scan_ticket_xml is not None else SCAN_TICKET_TEMPLATE_XML
    from_line = f"""    <wsa:From>
      <wsa:Address>{from_address}</wsa:Address>
    </wsa:From>
""" if from_address else ""
    destination_token_xml = (
        f"      <sca:DestinationToken>{destination_token}</sca:DestinationToken>\n"
        if destination_token
        else ""
    )
    scan_identifier_xml = (
        f"      <sca:ScanIdentifier>{scan_identifier}</sca:ScanIdentifier>\n"
        if scan_identifier
        else ""
    )
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:sca="{NS_SCA}">
  <soap:Header>
    <wsa:Action>{ACTION_CREATE_SCAN_JOB}</wsa:Action>
    <wsa:To>{to_url}</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
{from_line}    <wsa:ReplyTo>
      <wsa:Address>{WSA_ANONYMOUS}</wsa:Address>
    </wsa:ReplyTo>
  </soap:Header>
  <soap:Body>
    <sca:CreateScanJobRequest>
{scan_identifier_xml}{destination_token_xml}{ticket_block}
    </sca:CreateScanJobRequest>
  </soap:Body>
</soap:Envelope>
"""
    return mid, body


def build_retrieve_image_request(
    *,
    to_url: str,
    job_id: str,
    job_token: str,
    document_description: str = DEFAULT_DOCUMENT_DESCRIPTION,
    message_id: str | None = None,
    from_address: str | None = None,
) -> tuple[str, str]:
    """Build WS-Scan RetrieveImage SOAP envelope."""
    mid = message_id or _new_message_id()
    from_line = f"""    <wsa:From>
      <wsa:Address>{from_address}</wsa:Address>
    </wsa:From>
""" if from_address else ""
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:sca="{NS_SCA}">
  <soap:Header>
    <wsa:Action>{ACTION_RETRIEVE_IMAGE}</wsa:Action>
    <wsa:To>{to_url}</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
{from_line}    <wsa:ReplyTo>
      <wsa:Address>{WSA_ANONYMOUS}</wsa:Address>
    </wsa:ReplyTo>
  </soap:Header>
  <soap:Body>
    <sca:RetrieveImageRequest>
      <sca:JobId>{job_id}</sca:JobId>
      <sca:JobToken>{job_token}</sca:JobToken>
      <sca:DocumentDescription>{document_description}</sca:DocumentDescription>
    </sca:RetrieveImageRequest>
  </soap:Body>
</soap:Envelope>
"""
    return mid, body


def build_get_scanner_elements_request(
    *,
    to_url: str,
    element_names: tuple[str, ...] = SCANNER_METADATA_ELEMENT_NAMES,
    message_id: str | None = None,
    from_address: str | None = None,
) -> tuple[str, str]:
    """Build WS-Scan GetScannerElements SOAP envelope."""
    mid = message_id or _new_message_id()
    from_line = f"""    <wsa:From>
      <wsa:Address>{from_address}</wsa:Address>
    </wsa:From>
""" if from_address else ""
    requested_elements_xml = "".join(
        f"      <sca:Name>{name}</sca:Name>\n" for name in element_names
    )
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:sca="{NS_SCA}">
  <soap:Header>
    <wsa:Action>{ACTION_GET_SCANNER_ELEMENTS}</wsa:Action>
    <wsa:To>{to_url}</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
{from_line}    <wsa:ReplyTo>
      <wsa:Address>{WSA_ANONYMOUS}</wsa:Address>
    </wsa:ReplyTo>
  </soap:Header>
  <soap:Body>
    <sca:GetScannerElementsRequest>
      <sca:RequestedElements>
{requested_elements_xml}      </sca:RequestedElements>
    </sca:GetScannerElementsRequest>
  </soap:Body>
</soap:Envelope>
"""
    return mid, body


def extract_subscribe_destination_tokens_by_client_context(text: str) -> dict[str, str]:
    """Parse all ``DestinationResponse`` entries: ``ClientContext`` -> ``DestinationToken``.

    Order matches document order; duplicate ``ClientContext`` values keep the first token.
    """
    block = DESTINATION_RESPONSES_BLOCK_PATTERN.search(text)
    if not block:
        return {}
    out: dict[str, str] = {}
    for dr in DESTINATION_RESPONSE_BLOCK_PATTERN.finditer(block.group(0)):
        segment = dr.group(0)
        cc_match = CLIENT_CONTEXT_PATTERN.search(segment)
        tok_match = DESTINATION_TOKEN_PATTERN.search(segment)
        if not cc_match or not tok_match:
            continue
        key = cc_match.group(1).strip()
        val = tok_match.group(1).strip()
        if key and val and key not in out:
            out[key] = val
    return out


def extract_subscribe_destination_token(text: str) -> str | None:
    """Extract first ``DestinationToken`` from ``DestinationResponses`` (backward compatibility).

    Prefer :func:`extract_subscribe_destination_tokens_by_client_context` when correlating by
    ``ClientContext`` from ``ScanAvailableEvent``.
    """
    mapping = extract_subscribe_destination_tokens_by_client_context(text)
    if mapping:
        return next(iter(mapping.values()))
    block = DESTINATION_RESPONSES_BLOCK_PATTERN.search(text)
    if not block:
        return None
    match = DESTINATION_TOKEN_PATTERN.search(block.group(0))
    return match.group(1).strip() if match else None


def parse_subscribe_response(text: str) -> dict[str, str | None]:
    """Extract subscription details from SOAP response body."""
    identifier_match = IDENTIFIER_PATTERN.search(text)
    expires_match = EXPIRES_PATTERN.search(text)
    tokens_map = extract_subscribe_destination_tokens_by_client_context(text)
    subscribe_destination_token = extract_subscribe_destination_token(text)
    return {
        "identifier": identifier_match.group(1).strip() if identifier_match else None,
        "expires": expires_match.group(1).strip() if expires_match else None,
        "subscribe_destination_token": subscribe_destination_token,
        "subscribe_destination_tokens": tokens_map if tokens_map else None,
    }


def parse_get_response(text: str) -> dict[str, str | None]:
    """Extract candidate subscribe endpoint from WS-Transfer response."""
    values = URI_TEXT_PATTERN.findall(text)
    subscribe_to = next((value for value in values if "/WDP/SCAN" in value), None)
    if not subscribe_to:
        subscribe_to = next((value for value in values if "WSDScanner" in value), None)
    return {"suggested_subscribe_to_url": subscribe_to}


def parse_soap_fault(text: str) -> dict[str, str | None]:
    """Extract fault code/subcode/reason from SOAP fault payload."""
    code_match = FAULT_CODE_PATTERN.search(text)
    subcode_match = FAULT_SUBCODE_PATTERN.search(text)
    reason_match = FAULT_REASON_PATTERN.search(text)
    return {
        "fault_code": code_match.group(1).strip() if code_match else None,
        "fault_subcode": subcode_match.group(1).strip() if subcode_match else None,
        "fault_reason": reason_match.group(1).strip() if reason_match else None,
    }


def _extract_named_element_xml(text: str, element_name: str) -> str | None:
    """Extract first matching XML block for a named WS-Scan element."""
    pattern = re.compile(
        rf"<(?:[A-Za-z0-9_]+:)?{re.escape(element_name)}(?:\s[^>]*)?>.*?</(?:[A-Za-z0-9_]+:)?{re.escape(element_name)}>",
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.group(0).strip()


VALIDATION_INFO_SELF_CLOSING_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ValidationInfo\b\s*/\s*>",
)


def _valid_ticket_from_validate_response(text: str) -> str | None:
    """Resolve ValidTicket when ValidationInfo is present (Epson-style) vs legacy Status-only."""
    vi_block = _extract_named_element_xml(text, "ValidationInfo")
    if vi_block is not None:
        vt = VALID_TICKET_PATTERN.search(vi_block)
        return vt.group(1).strip().lower() if vt else "false"
    if VALIDATION_INFO_SELF_CLOSING_PATTERN.search(text):
        return "false"
    vt = VALID_TICKET_PATTERN.search(text)
    return vt.group(1).strip().lower() if vt else None


def parse_validate_scan_ticket_response(text: str) -> dict[str, str | None]:
    """Extract status and SOAP fault details from ValidateScanTicketResponse."""
    status_match = VALIDATE_STATUS_PATTERN.search(text)
    destination_token_match = DESTINATION_TOKEN_PATTERN.search(text)
    details = parse_soap_fault(text)
    details["status"] = status_match.group(1).strip() if status_match else None
    details["valid_ticket"] = _valid_ticket_from_validate_response(text)
    details["destination_token"] = (
        destination_token_match.group(1).strip() if destination_token_match else None
    )
    return details


def parse_create_scan_job_response(text: str) -> dict[str, str | None]:
    """Extract job id, job token, and SOAP fault details from CreateScanJobResponse."""
    job_match = JOB_ID_PATTERN.search(text)
    job_token_match = JOB_TOKEN_PATTERN.search(text)
    details = parse_soap_fault(text)
    details["job_id"] = job_match.group(1).strip() if job_match else None
    details["job_token"] = job_token_match.group(1).strip() if job_token_match else None
    return details


def parse_retrieve_image_response(text: str) -> dict[str, str | None]:
    """Extract status and SOAP fault details from RetrieveImageResponse."""
    status_match = STATUS_PATTERN.search(text)
    details = parse_soap_fault(text)
    details["status"] = status_match.group(1).strip() if status_match else None
    return details


def _format_embedded_scan_ticket_xml(scan_ticket_element: str) -> str:
    """Indent a ScanTicket element for ValidateScanTicket / CreateScanJob bodies (6 spaces)."""
    lines = scan_ticket_element.strip().splitlines()
    out: list[str] = []
    for line in lines:
        if not line.strip():
            out.append("")
        else:
            out.append(f"      {line.strip()}")
    return "\n".join(out)


_INPUT_SOURCE_INNER_PATTERN = re.compile(
    r"(<(?:[A-Za-z0-9_]+:)?InputSource(?:\s[^>]*)?>)\s*([^<]+?)\s*(</(?:[A-Za-z0-9_]+:)?InputSource>)",
    re.DOTALL,
)


def _scanner_configuration_enabled_input_sources(scanner_configuration_xml: str) -> tuple[str, ...]:
    """Return ``Platen`` / ``ADF`` / ``Feeder`` names that are explicitly ``true`` in configuration."""
    enabled: list[str] = []
    for name in ("Platen", "ADF", "Feeder"):
        if re.search(
            rf"<(?:[A-Za-z0-9_]+:)?{name}\b[^>]*>\s*true\s*</",
            scanner_configuration_xml,
            re.IGNORECASE | re.DOTALL,
        ):
            enabled.append(name)
    return tuple(enabled)


def _apply_scanner_configuration_to_scan_ticket_xml(
    scan_ticket_block: str,
    scanner_configuration_xml: str | None,
) -> str:
    """Align ``DocumentParameters`` / ``InputSource`` with ``ScannerConfiguration`` when they conflict."""
    if not scanner_configuration_xml or not scanner_configuration_xml.strip():
        return scan_ticket_block
    enabled = _scanner_configuration_enabled_input_sources(scanner_configuration_xml)
    if not enabled:
        return scan_ticket_block
    m = _INPUT_SOURCE_INNER_PATTERN.search(scan_ticket_block)
    if not m:
        return scan_ticket_block
    requested = m.group(2).strip()
    if requested in enabled:
        return scan_ticket_block
    replacement = enabled[0]
    return scan_ticket_block[: m.start(2)] + replacement + scan_ticket_block[m.end(2) :]


def resolve_scan_ticket_xml_for_chain(
    default_scan_ticket_fragment: str | None,
    scanner_configuration_fragment: str | None = None,
) -> str:
    """Prefer inner ``ScanTicket`` from ``DefaultScanTicket``; merge ``ScannerConfiguration`` when present."""
    if not (default_scan_ticket_fragment and default_scan_ticket_fragment.strip()):
        base = SCAN_TICKET_TEMPLATE_XML
    else:
        inner = _extract_named_element_xml(default_scan_ticket_fragment.strip(), "ScanTicket")
        if not inner:
            base = SCAN_TICKET_TEMPLATE_XML
        else:
            base = _format_embedded_scan_ticket_xml(inner)
    return _apply_scanner_configuration_to_scan_ticket_xml(base, scanner_configuration_fragment)


def parse_get_scanner_elements_response(text: str) -> dict[str, str | None]:
    """Extract known scanner metadata blocks and SOAP fault details."""
    details = parse_soap_fault(text)
    details["scanner_description"] = _extract_named_element_xml(text, "ScannerDescription")
    details["default_scan_ticket"] = _extract_named_element_xml(text, "DefaultScanTicket")
    details["scanner_configuration"] = _extract_named_element_xml(text, "ScannerConfiguration")
    details["scanner_status"] = _extract_named_element_xml(text, "ScannerStatus")
    return details


def resolve_wdp_scan_url(scanner_xaddr: str) -> str:
    """Resolve scanner WS-Scan endpoint by replacing endpoint path with /WDP/SCAN."""
    uri = URI_TEXT_PATTERN.search(scanner_xaddr)
    if not uri:
        return scanner_xaddr
    value = uri.group(0)
    parts = value.split("/", 3)
    if len(parts) < 3:
        return value
    return f"{parts[0]}//{parts[2]}/WDP/SCAN"


def extract_destination_token(text: str) -> str | None:
    """Extract destination token from SOAP payload if present."""
    match = DESTINATION_TOKEN_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip()


def extract_client_context(text: str) -> str | None:
    """Extract ``ClientContext`` from ``ScanAvailableEvent`` or ``DestinationResponse`` payload."""
    match = CLIENT_CONTEXT_PATTERN.search(text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def resolve_subscribe_destination_token_for_chain(
    *,
    event_payload: str,
    subscribe_destination_tokens: dict[str, str] | None,
    subscribe_destination_token: str | None,
    use_env_subscribe_destination_token_only: bool,
) -> str | None:
    """Pick ``DestinationToken`` from SubscribeResponse: env override, ClientContext map, or fallback."""
    explicit = (subscribe_destination_token or "").strip() or None
    tokens_map = dict(subscribe_destination_tokens or {})

    if use_env_subscribe_destination_token_only and explicit:
        return explicit

    cc = extract_client_context(event_payload)
    if cc and cc in tokens_map:
        return tokens_map[cc]

    if tokens_map:
        return next(iter(tokens_map.values()))

    return explicit


def extract_soap_envelope_message_id(text: str) -> str | None:
    """Extract outbound ``wsa:MessageID`` from a full SOAP envelope (e.g. ValidateScanTicketResponse).

    Used as a fallback for ``CreateScanJob`` ``DestinationToken`` when the spec-primary token from
    ``SubscribeResponse`` ``DestinationResponses`` is unavailable; some Win10 traces use this value
    from the validate response instead of body ``DestinationToken`` alone.
    """
    match = WSA_MESSAGE_ID_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip()


def extract_scan_identifier(text: str) -> str | None:
    """Extract scan identifier from SOAP payload if present."""
    match = SCAN_IDENTIFIER_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip()


def extract_event_subscription_identifier(text: str) -> str | None:
    """Extract WS-Eventing subscription ``Identifier`` from a notify envelope (e.g. ``ScanAvailableEvent``).

    Matches ``wse:Identifier`` / ``wsman:Identifier`` used as the subscription manager reference; aligns
    ``CreateScanJob`` ``DestinationToken`` with doc “token returned when the client subscribed” when
    the printer echoes it on the event.
    """
    match = IDENTIFIER_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip()


async def _post_soap(
    *,
    url: str,
    payload: str,
    timeout_sec: float,
) -> tuple[int, str]:
    """POST SOAP payload and return status and response text."""
    headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
    req_action = _extract_wsa_action(payload)
    req_action_short = _soap_action_short(req_action)
    req_mid_m = WSA_MESSAGE_ID_PATTERN.search(payload)
    req_message_id = req_mid_m.group(1).strip() if req_mid_m else None
    log.info(
        f"{req_action_short or 'unknown'}",
        extra={
            "soap_leg": "client_request",
            "soap_action": req_action_short,
            "wsa_message_id": req_message_id,
            "url": url,
            "bytes": len(payload.encode("utf-8")),
            "timeout_sec": timeout_sec,
        },
    )
    try:
        async with ClientSession() as session:
            async with session.post(
                url,
                data=payload.encode("utf-8"),
                headers=headers,
                timeout=timeout_sec,
            ) as response:
                text = await response.text()
                resp_action = _extract_wsa_action(text)
                resp_action_short = _soap_action_short(resp_action)
                resp_mid_m = WSA_MESSAGE_ID_PATTERN.search(text)
                resp_message_id = resp_mid_m.group(1).strip() if resp_mid_m else None
                fault = parse_soap_fault(text)
                resp_extra: dict[str, str | int | float | None] = {
                    "soap_leg": "client_response",
                    "soap_action": resp_action_short,
                    "wsa_message_id": resp_message_id,
                    "url": url,
                    "http_status": response.status,
                    "bytes": len(text.encode("utf-8")),
                }
                if fault.get("fault_subcode"):
                    resp_extra["fault_subcode"] = fault["fault_subcode"]
                if fault.get("fault_reason"):
                    resp_extra["fault_reason"] = fault["fault_reason"]
                log.info(f"{resp_action_short or 'unknown'}", extra=resp_extra)
                if response.status < 200 or response.status >= 300 or fault.get("fault_code"):
                    warn_extra = {**resp_extra, "fault_code": fault.get("fault_code")}
                    log.warning(
                        f"{resp_action_short or 'unknown'} indicates failure",
                        extra=warn_extra,
                    )
                return response.status, text
    except asyncio.TimeoutError:
        log.warning(
            f"{req_action_short or 'unknown'} timed out",
            extra={
                "soap_leg": "client_response",
                "soap_action": req_action_short,
                "wsa_message_id": req_message_id,
                "url": url,
                "timeout_sec": timeout_sec,
            },
        )
        raise
    except ClientError as exc:
        log.warning(
            f"{req_action_short or 'unknown'} transport error",
            extra={
                "soap_leg": "client_response",
                "soap_action": req_action_short,
                "wsa_message_id": req_message_id,
                "url": url,
                "error": str(exc),
            },
        )
        raise


async def preflight_get_scanner_capabilities(
    *,
    scanner_xaddr: str,
    timeout_sec: float = 5.0,
    get_to_url: str | None = None,
    from_address: str | None = None,
) -> dict[str, str | None]:
    """Query scanner capabilities and parse helpful endpoint hints."""
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
) -> dict[str, str | None]:
    """Send WS-Eventing Subscribe request to scanner endpoint."""
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
                "subscribe_destination_token": details.get("subscribe_destination_token"),
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


def _get_scanner_elements_should_retry_after_invalid_args(
    status: int,
    details: dict[str, str | None],
) -> bool:
    """Return True when a narrower element list may succeed (Epson-style strict QName checks)."""
    if 200 <= status < 300 and not details.get("fault_code"):
        return False
    sub = details.get("fault_subcode") or ""
    return "InvalidArgs" in sub


async def get_scanner_elements_metadata(
    *,
    scanner_xaddr: str,
    timeout_sec: float = 5.0,
    get_to_url: str | None = None,
    from_address: str | None = None,
) -> dict[str, str | None]:
    """Query scanner metadata using WS-Scan GetScannerElements."""
    target_url = get_to_url or resolve_wdp_scan_url(scanner_xaddr)

    async def _fetch(element_names: tuple[str, ...]) -> tuple[int, str, dict[str, str | None], str]:
        message_id, payload = build_get_scanner_elements_request(
            to_url=target_url,
            element_names=element_names,
            from_address=from_address,
        )
        status, response_text = await _post_soap(
            url=target_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        parsed = parse_get_scanner_elements_response(response_text)
        return status, response_text, parsed, message_id

    message_id: str = ""
    log.info(
        "Outbound WS-Scan GetScannerElements sending",
        extra={
            "scanner_xaddr": scanner_xaddr,
            "target_url": target_url,
            "timeout_sec": timeout_sec,
            "requested_element_count": len(SCANNER_METADATA_ELEMENT_NAMES),
        },
    )
    status, _, details, message_id = await _fetch(SCANNER_METADATA_ELEMENT_NAMES)
    details.update({"status": str(status), "message_id": message_id})

    if _get_scanner_elements_should_retry_after_invalid_args(status, details):
        log.info(
            "Outbound WS-Scan GetScannerElements retrying with reduced QName set",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "target_url": target_url,
                "first_fault_subcode": details.get("fault_subcode"),
            },
        )
        status2, _, details2, message_id2 = await _fetch(
            SCANNER_METADATA_ELEMENT_NAMES_NO_DEFAULT_TICKET
        )
        details2.update({"status": str(status2), "message_id": message_id2})
        details = details2
        status = status2
        message_id = message_id2
        if 200 <= status2 < 300 and not details2.get("fault_code"):
            dt_mid: str
            dt_status, _, dt_details, dt_mid = await _fetch(
                (f"{SCANNER_METADATA_ELEMENT_PREFIX}:DefaultScanTicket",)
            )
            dt_details.update({"status": str(dt_status), "message_id": dt_mid})
            if (
                200 <= dt_status < 300
                and not dt_details.get("fault_code")
                and dt_details.get("default_scan_ticket")
            ):
                details["default_scan_ticket"] = dt_details["default_scan_ticket"]

    if status < 200 or status >= 300:
        log.warning(
            "Outbound WS-Scan GetScannerElements returned non-success status",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "target_url": target_url,
                "status": status,
                "fault_subcode": details.get("fault_subcode"),
                "fault_reason": details.get("fault_reason"),
            },
        )
    log.info(
        "Outbound WS-Scan GetScannerElements completed",
        extra={
            "scanner_xaddr": scanner_xaddr,
            "target_url": target_url,
            "status": status,
            "message_id": message_id,
            "has_scanner_description": bool(details.get("scanner_description")),
            "has_default_scan_ticket": bool(details.get("default_scan_ticket")),
            "has_scanner_configuration": bool(details.get("scanner_configuration")),
            "has_scanner_status": bool(details.get("scanner_status")),
            "fault_subcode": details.get("fault_subcode"),
        },
    )
    return details


async def run_scan_available_chain(
    *,
    scanner_xaddr: str,
    scan_available_payload: str | None = None,
    timeout_sec: float = 5.0,
    from_address: str | None = None,
    eventing_subscription_identifier: str | None = None,
    subscribe_destination_token: str | None = None,
    subscribe_destination_tokens: dict[str, str] | None = None,
    use_env_subscribe_destination_token_only: bool = False,
    retry_create_without_destination_token_on_invalid_token: bool = True,
) -> dict[str, str | None]:
    """Execute ValidateScanTicket, CreateScanJob, then RetrieveImage."""
    target_url = resolve_wdp_scan_url(scanner_xaddr)
    scanner_metadata: dict[str, str | None] = {
        "probe_http_status": None,
        "probe_message_id": None,
        "probe_fault_code": None,
        "probe_fault_subcode": None,
        "probe_fault_reason": None,
        "scanner_description": None,
        "default_scan_ticket": None,
        "scanner_configuration": None,
        "scanner_status": None,
    }
    try:
        metadata_details = await get_scanner_elements_metadata(
            scanner_xaddr=scanner_xaddr,
            get_to_url=target_url,
            timeout_sec=timeout_sec,
            from_address=from_address,
        )
        scanner_metadata.update(
            {
                "probe_http_status": metadata_details.get("status"),
                "probe_message_id": metadata_details.get("message_id"),
                "probe_fault_code": metadata_details.get("fault_code"),
                "probe_fault_subcode": metadata_details.get("fault_subcode"),
                "probe_fault_reason": metadata_details.get("fault_reason"),
                "scanner_description": metadata_details.get("scanner_description"),
                "default_scan_ticket": metadata_details.get("default_scan_ticket"),
                "scanner_configuration": metadata_details.get("scanner_configuration"),
                "scanner_status": metadata_details.get("scanner_status"),
            }
        )
    except (asyncio.TimeoutError, ClientError) as exc:
        log.warning(
            "Scanner metadata probe failed; continuing scan chain",
            extra={"target_url": target_url, "error": str(exc)},
        )
    scan_ticket_xml = resolve_scan_ticket_xml_for_chain(
        scanner_metadata.get("default_scan_ticket"),
        scanner_metadata.get("scanner_configuration"),
    )
    validate_message_id, validate_payload = build_validate_scan_ticket_request(
        to_url=target_url,
        from_address=from_address,
        scan_ticket_xml=scan_ticket_xml,
    )
    validate_status, validate_response_text = await _post_soap(
        url=target_url,
        payload=validate_payload,
        timeout_sec=timeout_sec,
    )
    validate_details = parse_validate_scan_ticket_response(validate_response_text)
    validate_response_message_id = extract_soap_envelope_message_id(validate_response_text)
    event_payload = scan_available_payload or ""
    scan_identifier = extract_scan_identifier(event_payload)
    subscription_token = (eventing_subscription_identifier or "").strip() or None
    event_subscription_identifier = extract_event_subscription_identifier(event_payload)
    sub_dest = resolve_subscribe_destination_token_for_chain(
        event_payload=event_payload,
        subscribe_destination_tokens=subscribe_destination_tokens,
        subscribe_destination_token=subscribe_destination_token,
        use_env_subscribe_destination_token_only=use_env_subscribe_destination_token_only,
    )
    event_client_context = extract_client_context(event_payload)
    # Precedence: SubscribeResponse tokens (per ClientContext when map present), then event hints,
    # then validate response (MessageID heuristic and body token), then persisted WS-Eventing id.
    destination_token = (
        sub_dest
        or extract_destination_token(event_payload)
        or event_subscription_identifier
        or validate_response_message_id
        or validate_details.get("destination_token")
        or subscription_token
    )
    validate_details["http_status"] = str(validate_status)
    validate_details["message_id"] = validate_message_id
    log.info(
        "ValidateScanTicket completed",
        extra={
            "target_url": target_url,
            "http_status": validate_status,
            "message_id": validate_message_id,
            "status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "subscribe_destination_token": sub_dest,
            "event_client_context": event_client_context,
            "validate_response_message_id": validate_response_message_id,
            "event_subscription_identifier": event_subscription_identifier,
            "subscription_fallback_token": subscription_token,
            "scan_identifier": scan_identifier,
            "fault_subcode": validate_details.get("fault_subcode"),
        },
    )
    valid_ticket = validate_details.get("valid_ticket")
    if (
        validate_status < 200
        or validate_status >= 300
        or validate_details.get("fault_code")
        or (valid_ticket is not None and valid_ticket != "true")
    ):
        return {
            "target_url": target_url,
            **scanner_metadata,
            "validate_http_status": str(validate_status),
            "validate_message_id": validate_message_id,
            "validate_status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "scan_identifier": scan_identifier,
            "fault_code": validate_details.get("fault_code"),
            "fault_subcode": validate_details.get("fault_subcode"),
            "fault_reason": validate_details.get("fault_reason"),
            "create_http_status": None,
            "create_message_id": None,
            "job_id": None,
            "retrieve_http_status": None,
            "retrieve_message_id": None,
            "retrieve_status": None,
            "retrieve_fault_code": None,
            "retrieve_fault_subcode": None,
            "retrieve_fault_reason": None,
            "retrieve_elapsed_sec": None,
        }

    create_message_id, create_payload = build_create_scan_job_request(
        to_url=target_url,
        destination_token=destination_token,
        scan_identifier=scan_identifier,
        from_address=from_address,
        scan_ticket_xml=scan_ticket_xml,
    )
    create_status, create_response_text = await _post_soap(
        url=target_url,
        payload=create_payload,
        timeout_sec=timeout_sec,
    )
    create_details = parse_create_scan_job_response(create_response_text)
    create_used_token = destination_token
    create_used_scan_identifier = scan_identifier
    create_fault_subcode = create_details.get("fault_subcode") or ""
    if (
        retry_create_without_destination_token_on_invalid_token
        and create_status >= 400
        and destination_token
        and create_fault_subcode.endswith(INVALID_DESTINATION_TOKEN_FAULT)
    ):
        # Some firmwares reject DestinationToken (e.g. wrong subscription id shape) but
        # still require ScanIdentifier from ScanAvailableEvent on device-initiated jobs.
        # Retry with DestinationToken omitted only — dropping ScanIdentifier produced requests
        # with only ScanTicket and repeated ClientErrorInvalidDestinationToken in field testing.
        # Gated by config (WSD_CREATE_SCAN_JOB_RETRY_INVALID_DESTINATION_TOKEN).
        log.info(
            "CreateScanJob retrying without DestinationToken after invalid destination token fault",
            extra={
                "target_url": target_url,
                "fault_subcode": create_fault_subcode,
                "original_message_id": create_message_id,
                "preserve_scan_identifier": bool(scan_identifier),
            },
        )
        create_message_id, create_payload = build_create_scan_job_request(
            to_url=target_url,
            destination_token=None,
            scan_identifier=scan_identifier,
            from_address=from_address,
            scan_ticket_xml=scan_ticket_xml,
        )
        create_status, create_response_text = await _post_soap(
            url=target_url,
            payload=create_payload,
            timeout_sec=timeout_sec,
        )
        create_details = parse_create_scan_job_response(create_response_text)
        create_used_token = None
        create_used_scan_identifier = scan_identifier

    log.info(
        "CreateScanJob completed",
        extra={
            "target_url": target_url,
            "http_status": create_status,
            "message_id": create_message_id,
            "job_id": create_details.get("job_id"),
            "destination_token": create_used_token,
            "scan_identifier": create_used_scan_identifier,
            "fault_subcode": create_details.get("fault_subcode"),
        },
    )
    create_failed = create_status < 200 or create_status >= 300 or bool(create_details.get("fault_code"))
    resolved_job_id = create_details.get("job_id")
    if create_failed or not resolved_job_id:
        return {
            "target_url": target_url,
            **scanner_metadata,
            "validate_http_status": str(validate_status),
            "validate_message_id": validate_message_id,
            "validate_status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "scan_identifier": scan_identifier,
            "fault_code": create_details.get("fault_code"),
            "fault_subcode": create_details.get("fault_subcode"),
            "fault_reason": create_details.get("fault_reason"),
            "create_http_status": str(create_status),
            "create_message_id": create_message_id,
            "job_id": resolved_job_id,
            "retrieve_http_status": None,
            "retrieve_message_id": None,
            "retrieve_status": None,
            "retrieve_fault_code": None,
            "retrieve_fault_subcode": None,
            "retrieve_fault_reason": None,
            "retrieve_elapsed_sec": None,
        }

    create_completed_monotonic = time.monotonic()
    create_job_token = create_details.get("job_token")
    if not create_job_token:
        log.info(
            "RetrieveImage skipped: CreateScanJobResponse omitted JobToken (spec requires it for pull)",
            extra={
                "target_url": target_url,
                "job_id": resolved_job_id,
                "create_message_id": create_message_id,
            },
        )
        return {
            "target_url": target_url,
            **scanner_metadata,
            "validate_http_status": str(validate_status),
            "validate_message_id": validate_message_id,
            "validate_status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "scan_identifier": scan_identifier,
            "fault_code": create_details.get("fault_code"),
            "fault_subcode": create_details.get("fault_subcode"),
            "fault_reason": create_details.get("fault_reason"),
            "create_http_status": str(create_status),
            "create_message_id": create_message_id,
            "job_id": resolved_job_id,
            "retrieve_http_status": None,
            "retrieve_message_id": None,
            "retrieve_status": None,
            "retrieve_fault_code": None,
            "retrieve_fault_subcode": None,
            "retrieve_fault_reason": None,
            "retrieve_elapsed_sec": None,
        }

    retrieve_message_id, retrieve_payload = build_retrieve_image_request(
        to_url=target_url,
        job_id=resolved_job_id,
        job_token=create_job_token,
        from_address=from_address,
    )
    retrieve_status, retrieve_response_text = await _post_soap(
        url=target_url,
        payload=retrieve_payload,
        timeout_sec=timeout_sec,
    )
    retrieve_details = parse_retrieve_image_response(retrieve_response_text)
    retrieve_elapsed_sec = time.monotonic() - create_completed_monotonic
    retrieve_fault_subcode = retrieve_details.get("fault_subcode") or ""
    log.info(
        "RetrieveImage completed",
        extra={
            "target_url": target_url,
            "http_status": retrieve_status,
            "message_id": retrieve_message_id,
            "job_id": resolved_job_id,
            "job_token": create_job_token,
            "fault_subcode": retrieve_details.get("fault_subcode"),
            "retrieve_elapsed_sec": round(retrieve_elapsed_sec, 6),
            "within_retrieve_window_60s": retrieve_elapsed_sec <= 60.0,
        },
    )
    if retrieve_elapsed_sec > 60.0:
        log.warning(
            "RetrieveImage exceeded 60s guideline after CreateScanJob",
            extra={
                "target_url": target_url,
                "job_id": resolved_job_id,
                "job_token": create_job_token,
                "retrieve_elapsed_sec": round(retrieve_elapsed_sec, 6),
            },
        )
    if "JobTimedOut" in retrieve_fault_subcode:
        log.warning(
            "RetrieveImage fault JobTimedOut",
            extra={
                "target_url": target_url,
                "job_id": resolved_job_id,
                "job_token": create_job_token,
                "fault_subcode": retrieve_fault_subcode,
            },
        )
    if "NoImagesAvailable" in retrieve_fault_subcode or "ClientErrorNoImagesAvailable" in retrieve_fault_subcode:
        log.warning(
            "RetrieveImage fault no images available",
            extra={
                "target_url": target_url,
                "job_id": resolved_job_id,
                "job_token": create_job_token,
                "fault_subcode": retrieve_fault_subcode,
            },
        )
    return {
        "target_url": target_url,
        **scanner_metadata,
        "validate_http_status": str(validate_status),
        "validate_message_id": validate_message_id,
        "validate_status": validate_details.get("status"),
        "valid_ticket": validate_details.get("valid_ticket"),
        "destination_token": destination_token,
        "scan_identifier": scan_identifier,
        "fault_code": create_details.get("fault_code"),
        "fault_subcode": create_details.get("fault_subcode"),
        "fault_reason": create_details.get("fault_reason"),
        "create_http_status": str(create_status),
        "create_message_id": create_message_id,
        "job_id": resolved_job_id,
        "retrieve_http_status": str(retrieve_status),
        "retrieve_message_id": retrieve_message_id,
        "retrieve_status": retrieve_details.get("status"),
        "retrieve_fault_code": retrieve_details.get("fault_code"),
        "retrieve_fault_subcode": retrieve_details.get("fault_subcode"),
        "retrieve_fault_reason": retrieve_details.get("fault_reason"),
        "retrieve_elapsed_sec": f"{retrieve_elapsed_sec:.6f}",
    }

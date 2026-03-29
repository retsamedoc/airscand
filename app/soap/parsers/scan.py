"""WS-Scan operations: request builders, response parsers, and scan-ticket helpers."""

from __future__ import annotations

import logging
import re

from app.destinations import ScanDestinationConfig
from app.soap.addressing import WSA_MESSAGE_ID_PATTERN
from app.soap.envelope import build_outbound_client_envelope
from app.soap.fault import parse_soap_fault
from app.soap.namespaces import (
    ACTION_CREATE_SCAN_JOB,
    ACTION_GET_JOB_STATUS,
    ACTION_GET_SCANNER_ELEMENTS,
    ACTION_RETRIEVE_IMAGE,
    ACTION_VALIDATE_SCAN_TICKET,
    NS_SCA,
)
from app.soap.parsers.capabilities import (
    InputSourceCapabilities,
    ScannerCapabilities,
    clamp_resolution_to_capabilities,
    input_source_capabilities_for_name,
    pick_color_entry,
)
from app.soap.parsers.eventing import (
    CLIENT_CONTEXT_PATTERN,
    DESTINATION_TOKEN_PATTERN,
    IDENTIFIER_PATTERN,
)
from app.soap.parsers.transfer import URI_TEXT_PATTERN

INVALID_DESTINATION_TOKEN_FAULT = "ClientErrorInvalidDestinationToken"
DEFAULT_DOCUMENT_NUMBER = "1"
GET_JOB_STATUS_INITIAL_INTERVAL_SEC = 0.25
GET_JOB_STATUS_MAX_INTERVAL_SEC = 2.0
GET_JOB_STATUS_MAX_WAIT_SEC = 120.0

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

JOB_ID_PATTERN = re.compile(r"<(?:[A-Za-z0-9_]+:)?JobId>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?JobId>")
JOB_TOKEN_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?JobToken>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?JobToken>"
)
CREATE_SCAN_JOB_RESPONSE_INNER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?CreateScanJobResponse\b[^>]*>(.*?)</(?:[A-Za-z0-9_]+:)?CreateScanJobResponse>",
    re.DOTALL | re.IGNORECASE,
)
GET_JOB_STATUS_RESPONSE_INNER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?GetJobStatusResponse\b[^>]*>(.*?)</(?:[A-Za-z0-9_]+:)?GetJobStatusResponse>",
    re.DOTALL | re.IGNORECASE,
)
JOB_STATE_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?JobState>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?JobState>",
    re.IGNORECASE,
)
JOB_STATUS_IMAGES_TO_TRANSFER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ImagesToTransfer[^>]*>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?ImagesToTransfer>",
    re.IGNORECASE,
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
STATUS_PATTERN = re.compile(r"<(?:[A-Za-z0-9_]+:)?Status>\s*([^<]+)\s*</(?:[A-Za-z0-9_]+:)?Status>")
SCAN_IDENTIFIER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ScanIdentifier>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?ScanIdentifier>"
)
SCANNER_STATUS_SUMMARY_EVENT_INNER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ScannerStatusSummaryEvent\b[^>]*>(.*?)</(?:[A-Za-z0-9_]+:)?ScannerStatusSummaryEvent>",
    re.DOTALL | re.IGNORECASE,
)
SCANNER_STATE_IN_STATUS_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?State>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?State>",
    re.IGNORECASE,
)

TICKET_INPUT_SOURCE_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?InputSource\b[^>]*>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?InputSource>",
    re.IGNORECASE,
)
TICKET_RESOLUTION_BLOCK_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Resolution\b[^>]*>(.*?)</(?:[A-Za-z0-9_]+:)?Resolution>",
    re.DOTALL | re.IGNORECASE,
)
TICKET_COLOR_PROCESSING_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ColorProcessing\b[^>]*>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?ColorProcessing>",
    re.IGNORECASE,
)
TICKET_SCAN_REGION_WIDTH_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ScanRegionWidth>\s*(\d+)\s*</(?:[A-Za-z0-9_]+:)?ScanRegionWidth>",
    re.IGNORECASE,
)
TICKET_SCAN_REGION_HEIGHT_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ScanRegionHeight>\s*(\d+)\s*</(?:[A-Za-z0-9_]+:)?ScanRegionHeight>",
    re.IGNORECASE,
)
TICKET_WIDTH_EL_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Width>\s*(\d+)\s*</(?:[A-Za-z0-9_]+:)?Width>",
    re.IGNORECASE,
)
TICKET_HEIGHT_EL_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Height>\s*(\d+)\s*</(?:[A-Za-z0-9_]+:)?Height>",
    re.IGNORECASE,
)

_log = logging.getLogger(__name__)

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

_INPUT_SOURCE_INNER_PATTERN = re.compile(
    r"(<(?:[A-Za-z0-9_]+:)?InputSource(?:\s[^>]*)?>)\s*([^<]+?)\s*(</(?:[A-Za-z0-9_]+:)?InputSource>)",
    re.DOTALL,
)
VALIDATION_INFO_SELF_CLOSING_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ValidationInfo\b\s*/\s*>",
)


def _extract_named_element_xml(text: str, element_name: str) -> str | None:
    """Extract first matching XML block for a named WS-Scan element."""
    pattern = re.compile(
        rf"<(?:[A-Za-z0-9_]+:)?{re.escape(element_name)}(?:\s[^>]*)?>.*?</(?:[A-Za-z0-9_]+:)?{re.escape(element_name)}>",
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(0).strip() if match else None


def build_validate_scan_ticket_request(
    *,
    to_url: str,
    message_id: str | None = None,
    from_address: str | None = None,
    scan_ticket_xml: str | None = None,
) -> tuple[str, str]:
    """Build WS-Scan ValidateScanTicket SOAP envelope."""
    ticket_block = scan_ticket_xml if scan_ticket_xml is not None else SCAN_TICKET_TEMPLATE_XML
    body_inner = f"""    <sca:ValidateScanTicketRequest>
{ticket_block}
    </sca:ValidateScanTicketRequest>"""
    return build_outbound_client_envelope(
        xmlns_extra={"sca": NS_SCA},
        action=ACTION_VALIDATE_SCAN_TICKET,
        to_url=to_url,
        body_inner_xml=body_inner,
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id="",
    )


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
    ticket_block = scan_ticket_xml if scan_ticket_xml is not None else SCAN_TICKET_TEMPLATE_XML
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
    body_inner = f"""    <sca:CreateScanJobRequest>
{scan_identifier_xml}{destination_token_xml}{ticket_block}
    </sca:CreateScanJobRequest>"""
    return build_outbound_client_envelope(
        xmlns_extra={"sca": NS_SCA},
        action=ACTION_CREATE_SCAN_JOB,
        to_url=to_url,
        body_inner_xml=body_inner,
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id="",
    )


def build_retrieve_image_request(
    *,
    to_url: str,
    job_id: str,
    job_token: str,
    document_number: str = DEFAULT_DOCUMENT_NUMBER,
    message_id: str | None = None,
    from_address: str | None = None,
) -> tuple[str, str]:
    """Build WS-Scan RetrieveImage SOAP envelope."""
    body_inner = f"""    <sca:RetrieveImageRequest>
      <sca:JobId>{job_id}</sca:JobId>
      <sca:JobToken>{job_token}</sca:JobToken>
      <sca:DocumentDescription>
        <sca:DocumentNumber>{document_number}</sca:DocumentNumber>
      </sca:DocumentDescription>
    </sca:RetrieveImageRequest>"""
    return build_outbound_client_envelope(
        xmlns_extra={"sca": NS_SCA},
        action=ACTION_RETRIEVE_IMAGE,
        to_url=to_url,
        body_inner_xml=body_inner,
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id="",
    )


def build_get_job_status_request(
    *,
    to_url: str,
    job_id: str,
    job_token: str,
    message_id: str | None = None,
    from_address: str | None = None,
) -> tuple[str, str]:
    """Build WS-Scan GetJobStatus SOAP envelope."""
    body_inner = f"""    <sca:GetJobStatusRequest>
      <sca:JobId>{job_id}</sca:JobId>
      <sca:JobToken>{job_token}</sca:JobToken>
    </sca:GetJobStatusRequest>"""
    return build_outbound_client_envelope(
        xmlns_extra={"sca": NS_SCA},
        action=ACTION_GET_JOB_STATUS,
        to_url=to_url,
        body_inner_xml=body_inner,
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id="",
    )


def build_get_scanner_elements_request(
    *,
    to_url: str,
    element_names: tuple[str, ...] = SCANNER_METADATA_ELEMENT_NAMES,
    message_id: str | None = None,
    from_address: str | None = None,
) -> tuple[str, str]:
    """Build WS-Scan GetScannerElements SOAP envelope."""
    requested_elements_xml = "".join(
        f"      <sca:Name>{name}</sca:Name>\n" for name in element_names
    )
    body_inner = f"""    <sca:GetScannerElementsRequest>
      <sca:RequestedElements>
{requested_elements_xml}      </sca:RequestedElements>
    </sca:GetScannerElementsRequest>"""
    return build_outbound_client_envelope(
        xmlns_extra={"sca": NS_SCA},
        action=ACTION_GET_SCANNER_ELEMENTS,
        to_url=to_url,
        body_inner_xml=body_inner,
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id="",
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
    details = parse_soap_fault(text)
    block_m = CREATE_SCAN_JOB_RESPONSE_INNER_PATTERN.search(text)
    search_scope = block_m.group(1) if block_m else text
    job_match = JOB_ID_PATTERN.search(search_scope)
    job_token_match = JOB_TOKEN_PATTERN.search(search_scope)
    details["job_id"] = job_match.group(1).strip() if job_match else None
    details["job_token"] = job_token_match.group(1).strip() if job_token_match else None
    return details


def parse_get_job_status_response(text: str) -> dict[str, str | None]:
    """Extract JobState, ImagesToTransfer, and SOAP fault details from GetJobStatusResponse."""
    details = parse_soap_fault(text)
    block_m = GET_JOB_STATUS_RESPONSE_INNER_PATTERN.search(text)
    scope = block_m.group(1) if block_m else text
    jm = JOB_STATE_PATTERN.search(scope)
    im = JOB_STATUS_IMAGES_TO_TRANSFER_PATTERN.search(scope)
    details["job_state"] = jm.group(1).strip() if jm else None
    details["images_to_transfer"] = im.group(1).strip() if im else None
    return details


def job_ready_for_retrieve_from_status(
    job_state: str | None,
    images_to_transfer: str | None,
) -> bool:
    """Return True when GetJobStatus indicates the pull client may call RetrieveImage."""
    s = (job_state or "").strip().lower()
    if "cancel" in s or "abort" in s:
        return False
    if s in ("error", "failed", "faulted"):
        return False
    if s in ("completed", "ready", "completedwitherrors", "imageavailable"):
        return True
    if "complete" in s and "incomplete" not in s:
        return True
    try:
        if int((images_to_transfer or "0").strip()) > 0:
            return True
    except ValueError:
        pass
    return False


def job_status_terminal_failure(job_state: str | None) -> bool:
    """Return True when the scan job will not produce retrievable images."""
    s = (job_state or "").strip().lower()
    if not s:
        return False
    if "cancel" in s or "abort" in s:
        return True
    if s in ("error", "failed", "faulted"):
        return True
    return False


def get_job_status_fault_implies_unsupported(
    http_status: int,
    details: dict[str, str | None],
) -> bool:
    """Heuristic: scanner does not implement GetJobStatus; caller may fall back to RetrieveImage only."""
    if http_status in (404, 405):
        return True
    if details.get("fault_code") and not details.get("job_state"):
        sub = (details.get("fault_subcode") or "").lower()
        reason = (details.get("fault_reason") or "").lower()
        if "notsupported" in sub or "actionnotsupported" in sub:
            return True
        if "not supported" in reason or "unknown action" in reason:
            return True
    return False


def parse_retrieve_image_response(text: str) -> dict[str, str | None]:
    """Extract status and SOAP fault details from RetrieveImageResponse."""
    status_match = STATUS_PATTERN.search(text)
    details = parse_soap_fault(text)
    details["status"] = status_match.group(1).strip() if status_match else None
    return details


def parse_scanner_status_summary_event(text: str) -> dict[str, str | None]:
    """Extract ``ScannerState`` from ``ScannerStatusSummaryEvent`` SOAP body."""
    block_m = SCANNER_STATUS_SUMMARY_EVENT_INNER_PATTERN.search(text)
    scope = block_m.group(1) if block_m else text
    sm = SCANNER_STATE_IN_STATUS_PATTERN.search(scope)
    return {"scanner_state": sm.group(1).strip() if sm else None}


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


apply_scanner_configuration_to_scan_ticket_xml = _apply_scanner_configuration_to_scan_ticket_xml


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


def _clamp_paper_to_capabilities(
    width: int,
    height: int,
    src_caps: InputSourceCapabilities | None,
) -> tuple[int, int]:
    """Clamp paper/region dimensions to scanner min/max when advertised."""
    if src_caps is None:
        return (width, height)
    out_w, out_h = width, height
    if src_caps.max_width is not None:
        out_w = min(out_w, src_caps.max_width)
    if src_caps.max_height is not None:
        out_h = min(out_h, src_caps.max_height)
    if src_caps.min_width is not None:
        out_w = max(out_w, src_caps.min_width)
    if src_caps.min_height is not None:
        out_h = max(out_h, src_caps.min_height)
    return (out_w, out_h)


def build_scan_ticket_from_destination_config(
    config: ScanDestinationConfig,
    caps: ScannerCapabilities | None,
) -> str:
    """Build a ``ScanTicket`` XML fragment from destination settings, clamped to capabilities."""
    src_caps = input_source_capabilities_for_name(caps, config.input_source)
    rw, rh = clamp_resolution_to_capabilities(config.dpi_width, config.dpi_height, src_caps)
    color = pick_color_entry(config.color_processing, src_caps)
    pw, ph = _clamp_paper_to_capabilities(config.paper_width, config.paper_height, src_caps)
    fmt = config.format
    src = config.input_source
    return f"""      <sca:ScanTicket>
        <sca:JobDescription>
          <sca:JobName>airscand destination scan</sca:JobName>
          <sca:JobOriginatingUserName>airscand</sca:JobOriginatingUserName>
          <sca:JobInformation>Scan from {src}</sca:JobInformation>
        </sca:JobDescription>
        <sca:DocumentParameters>
          <sca:Format sca:MustHonor="true">{fmt}</sca:Format>
          <sca:ImagesToTransfer sca:MustHonor="true">1</sca:ImagesToTransfer>
          <sca:InputSource sca:MustHonor="true">{src}</sca:InputSource>
          <sca:InputSize sca:MustHonor="true">
            <sca:InputMediaSize>
              <sca:Width>{pw}</sca:Width>
              <sca:Height>{ph}</sca:Height>
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
                <sca:ScanRegionWidth>{pw}</sca:ScanRegionWidth>
                <sca:ScanRegionHeight>{ph}</sca:ScanRegionHeight>
              </sca:ScanRegion>
              <sca:ColorProcessing sca:MustHonor="true">{color}</sca:ColorProcessing>
              <sca:Resolution sca:MustHonor="true">
                <sca:Width>{rw}</sca:Width>
                <sca:Height>{rh}</sca:Height>
              </sca:Resolution>
            </sca:MediaFront>
          </sca:MediaSides>
        </sca:DocumentParameters>
      </sca:ScanTicket>"""


def validate_scan_ticket_against_capabilities(
    scan_ticket_xml: str,
    caps: ScannerCapabilities | None,
) -> dict[str, object]:
    """Check ticket resolution, color, and region against parsed scanner capabilities.

    Logs a warning for each issue. Validation is advisory: callers still send the ticket.

    Args:
        scan_ticket_xml: Inner or full XML containing ``ScanTicket`` content.
        caps: Parsed capabilities, or None when metadata was unavailable.

    Returns:
        Dict with ``ok`` (bool), ``issues`` (list of short machine-readable codes), and
        ``warnings`` (same strings, for structured logging).
    """
    issues: list[str] = []
    if caps is None:
        return {"ok": True, "issues": issues, "warnings": list(issues)}

    src_m = TICKET_INPUT_SOURCE_PATTERN.search(scan_ticket_xml)
    input_source = src_m.group(1).strip() if src_m else "Platen"
    sc = input_source_capabilities_for_name(caps, input_source)
    if sc is None:
        issues.append(f"unknown_input_source:{input_source}")
    elif not sc.enabled:
        issues.append(f"input_source_disabled:{input_source}")

    res_m = TICKET_RESOLUTION_BLOCK_PATTERN.search(scan_ticket_xml)
    if res_m:
        inner = res_m.group(1) or ""
        wm = TICKET_WIDTH_EL_PATTERN.search(inner)
        hm = TICKET_HEIGHT_EL_PATTERN.search(inner)
        if wm and hm:
            rw, rh = int(wm.group(1)), int(hm.group(1))
            if sc and sc.resolutions and (rw, rh) not in sc.resolutions:
                issues.append(f"resolution_not_listed:{rw}x{rh}")

    col_m = TICKET_COLOR_PROCESSING_PATTERN.search(scan_ticket_xml)
    if col_m and sc and sc.color_entries:
        col = col_m.group(1).strip()
        if col not in sc.color_entries:
            issues.append(f"color_not_listed:{col}")

    rw_m = TICKET_SCAN_REGION_WIDTH_PATTERN.search(scan_ticket_xml)
    rh_m = TICKET_SCAN_REGION_HEIGHT_PATTERN.search(scan_ticket_xml)
    if rw_m and rh_m and sc:
        rww, rhh = int(rw_m.group(1)), int(rh_m.group(1))
        if sc.min_width is not None and rww < sc.min_width:
            issues.append(f"scan_region_width_below_min:{rww}<{sc.min_width}")
        if sc.min_height is not None and rhh < sc.min_height:
            issues.append(f"scan_region_height_below_min:{rhh}<{sc.min_height}")
        if sc.max_width is not None and rww > sc.max_width:
            issues.append(f"scan_region_width_above_max:{rww}>{sc.max_width}")
        if sc.max_height is not None and rhh > sc.max_height:
            issues.append(f"scan_region_height_above_max:{rhh}>{sc.max_height}")

    for code in issues:
        _log.warning(
            "Scan ticket does not match advertised capabilities",
            extra={"scan_ticket_issue": code},
        )

    return {"ok": not issues, "issues": issues, "warnings": list(issues)}


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
    return match.group(1).strip() if match else None


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
    """Extract outbound ``wsa:MessageID`` from a full SOAP envelope."""
    match = WSA_MESSAGE_ID_PATTERN.search(text)
    return match.group(1).strip() if match else None


def extract_scan_identifier(text: str) -> str | None:
    """Extract scan identifier from SOAP payload if present."""
    match = SCAN_IDENTIFIER_PATTERN.search(text)
    return match.group(1).strip() if match else None


def extract_event_subscription_identifier(text: str) -> str | None:
    """Extract WS-Eventing subscription ``Identifier`` from a notify envelope."""
    match = IDENTIFIER_PATTERN.search(text)
    return match.group(1).strip() if match else None

"""Parse inbound WS-Eventing Subscribe/Renew bodies and management headers."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from app.soap.parsers.eventing import IDENTIFIER_PATTERN, parse_iso8601_duration_to_seconds

__all__ = [
    "PUSH_DELIVERY_MODE_URI",
    "extract_management_subscription_identifier",
    "extract_wsa_to_optional",
    "inbound_subscribe_expires_fault_reason",
    "parse_inbound_renew_expires_optional",
    "parse_inbound_subscribe_body",
    "seconds_to_xs_duration",
    "grant_expires_from_request",
]

# Canonical Push mode URI (case-insensitive compare).
PUSH_DELIVERY_MODE_URI = "http://schemas.xmlsoap.org/ws/2004/08/eventing/DeliveryModes/Push"

_HEADER_INNER_PATTERN = re.compile(
    r"<(?:[^:>\s]+:)?Header\b[^>]*>(.*)</(?:[^:>\s]+:)?Header>",
    re.DOTALL | re.IGNORECASE,
)
_WSA_TO_PATTERN = re.compile(
    r"<(?:[^:>\s]+:)?To\b[^>]*>\s*([^<]+?)\s*</(?:[^:>\s]+:)?To>",
    re.DOTALL | re.IGNORECASE,
)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child_by_local(parent: ET.Element, local: str) -> ET.Element | None:
    for ch in parent:
        if _local_name(ch.tag) == local:
            return ch
    return None


def _text_direct(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def extract_wsa_to_optional(soap_text: str) -> str | None:
    """Return first ``wsa:To`` in the SOAP header, if any."""
    m = _HEADER_INNER_PATTERN.search(soap_text)
    segment = m.group(1) if m else soap_text
    to_m = _WSA_TO_PATTERN.search(segment)
    return to_m.group(1).strip() if to_m else None


def extract_management_subscription_identifier(soap_text: str) -> str | None:
    """Extract subscription id from the SOAP header (Renew/Unsubscribe/GetStatus pattern)."""
    m = _HEADER_INNER_PATTERN.search(soap_text)
    segment = m.group(1) if m else soap_text
    id_m = IDENTIFIER_PATTERN.search(segment)
    return id_m.group(1).strip() if id_m else None


@dataclass(frozen=True)
class ParsedInboundSubscribe:
    """Fields needed to validate an inbound ``Subscribe``."""

    delivery_mode: str | None
    notify_to_address: str
    has_end_to: bool
    end_to_address: str
    end_to_reference_parameters_xml: str | None
    requested_expires: str | None
    has_filter: bool


def normalize_eventing_epr_address(addr: str) -> str:
    """Normalize sink/manager addresses for equality checks (trim, strip trailing slash)."""
    return (addr or "").strip().rstrip("/")


def inbound_subscribe_expires_fault_reason(requested_expires: str | None) -> str | None:
    """Return a human-readable fault reason if ``Expires`` is present but invalid.

    Missing or empty ``Expires`` is valid (server chooses a grant). Non-empty values
    must parse as a positive ISO-8601 duration.

    Args:
        requested_expires: Raw ``wse:Expires`` text from the subscribe body, if any.

    Returns:
        ``None`` when the value is absent/empty or usable; otherwise a short reason
        string for ``InvalidExpirationTime`` SOAP faults.
    """
    raw = (requested_expires or "").strip()
    if not raw:
        return None
    try:
        sec = parse_iso8601_duration_to_seconds(raw)
    except ValueError:
        return "wse:Expires is not a valid xs:duration"
    if sec <= 0:
        return "wse:Expires must be a positive duration"
    return None


def parse_inbound_subscribe_body(soap_text: str) -> ParsedInboundSubscribe | None:
    """Parse ``wse:Subscribe`` under ``soap:Body``; return ``None`` if missing or malformed."""
    try:
        root = ET.fromstring(soap_text)
    except ET.ParseError:
        return None
    body: ET.Element | None = None
    for ch in root:
        if _local_name(ch.tag) == "Body":
            body = ch
            break
    if body is None:
        return None
    subscribe_el: ET.Element | None = None
    for ch in body:
        if _local_name(ch.tag) == "Subscribe":
            subscribe_el = ch
            break
    if subscribe_el is None:
        return None

    delivery_el = _child_by_local(subscribe_el, "Delivery")
    mode: str | None = None
    if delivery_el is not None:
        mode = (delivery_el.get("Mode") or "").strip() or None

    notify_el = _child_by_local(delivery_el, "NotifyTo") if delivery_el is not None else None
    addr_el = _child_by_local(notify_el, "Address") if notify_el is not None else None
    notify_addr = _text_direct(addr_el)

    end_el = _child_by_local(subscribe_el, "EndTo")
    end_addr_el = _child_by_local(end_el, "Address") if end_el is not None else None
    end_addr = _text_direct(end_addr_el)
    has_end_to = end_el is not None
    end_ref_xml: str | None = None
    if end_el is not None:
        ref_el = _child_by_local(end_el, "ReferenceParameters")
        if ref_el is not None:
            end_ref_xml = ET.tostring(ref_el, encoding="unicode").strip() or None

    expires_el = _child_by_local(subscribe_el, "Expires")
    requested_expires = _text_direct(expires_el) or None

    has_filter = _child_by_local(subscribe_el, "Filter") is not None

    return ParsedInboundSubscribe(
        delivery_mode=mode,
        notify_to_address=notify_addr,
        has_end_to=has_end_to,
        end_to_address=end_addr,
        end_to_reference_parameters_xml=end_ref_xml,
        requested_expires=requested_expires,
        has_filter=has_filter,
    )


def parse_inbound_renew_expires_optional(soap_text: str) -> str | None:
    """Return ``wse:Expires`` text inside ``wse:Renew`` if present."""
    try:
        root = ET.fromstring(soap_text)
    except ET.ParseError:
        return None
    body: ET.Element | None = None
    for ch in root:
        if _local_name(ch.tag) == "Body":
            body = ch
            break
    if body is None:
        return None
    renew_el: ET.Element | None = None
    for ch in body:
        if _local_name(ch.tag) == "Renew":
            renew_el = ch
            break
    if renew_el is None:
        return None
    exp_el = _child_by_local(renew_el, "Expires")
    return _text_direct(exp_el) or None


def seconds_to_xs_duration(sec: float) -> str:
    """Format a non-negative duration in seconds as ``xs:duration`` (PT… form)."""
    s = max(1, int(round(float(sec))))
    if s % 3600 == 0:
        return f"PT{s // 3600}H"
    if s % 60 == 0:
        return f"PT{s // 60}M"
    return f"PT{s}S"


def grant_expires_from_request(
    requested: str | None,
    *,
    default_duration: str = "PT1H",
    max_seconds: float = 86400.0,
) -> tuple[str, float]:
    """Choose granted ``wse:Expires`` string and lease length in seconds."""
    try:
        default_sec = parse_iso8601_duration_to_seconds(default_duration)
    except ValueError:
        default_duration = "PT1H"
        default_sec = 3600.0
    raw = (requested or "").strip()
    if not raw:
        return default_duration, min(default_sec, max_seconds)
    try:
        req_sec = parse_iso8601_duration_to_seconds(raw)
    except ValueError:
        return default_duration, min(default_sec, max_seconds)
    if req_sec <= 0:
        return default_duration, min(default_sec, max_seconds)
    granted_sec = min(req_sec, max_seconds)
    granted_str = raw if granted_sec == req_sec else seconds_to_xs_duration(granted_sec)
    return granted_str, granted_sec

"""Parse inbound WS-Eventing Subscribe and management headers for the local subscription manager."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from app.soap.namespaces import (
    FILTER_DIALECT_DEVPROF_ACTION,
    NS_SOAP,
    SCAN_AVAILABLE_EVENT_ACTION,
    SCANNER_STATUS_SUMMARY_EVENT_ACTION,
    WSE_DELIVERY_MODE_PUSH,
)
from app.soap.parsers.eventing import EXPIRES_PATTERN, parse_iso8601_duration_to_seconds

_SUPPORTED_FILTER_ACTIONS = frozenset(
    {
        SCAN_AVAILABLE_EVENT_ACTION,
        SCANNER_STATUS_SUMMARY_EVENT_ACTION,
    }
)


@dataclass(frozen=True)
class InboundSubscribeAnalysis:
    """Outcome of validating an inbound ``Subscribe`` body."""

    fault_subcode: str | None
    fault_reason: str | None
    granted_seconds: float
    granted_expires_str: str

    @property
    def ok(self) -> bool:
        """Return True when the subscribe should succeed."""
        return self.fault_subcode is None


def extract_subscription_identifier_from_soap_headers(soap_text: str) -> str | None:
    """Return the first ``wse:Identifier`` (or unprefixed ``Identifier``) in the SOAP Header.

    Renew / GetStatus / Unsubscribe requests carry the subscription id in the header block
    (before ``soap:Body``), matching how :func:`app.soap.builders.eventing.build_renew_request`
    serializes outbound management calls.
    """
    lower = soap_text.lower()
    idx_body = lower.find("<soap:body")
    if idx_body == -1:
        idx_body = lower.find("<body")
    head = soap_text[:idx_body] if idx_body != -1 else soap_text
    m = re.search(
        r"<(?:[^:>/\s]+:)?Identifier>\s*([^<\s]+)\s*</(?:[^:>/\s]+:)?Identifier>",
        head,
        re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _fault(granted: float, granted_str: str, subcode: str, reason: str) -> InboundSubscribeAnalysis:
    return InboundSubscribeAnalysis(
        fault_subcode=subcode,
        fault_reason=reason,
        granted_seconds=granted,
        granted_expires_str=granted_str,
    )


def _ok(granted_seconds: float, granted_str: str) -> InboundSubscribeAnalysis:
    return InboundSubscribeAnalysis(
        fault_subcode=None,
        fault_reason=None,
        granted_seconds=granted_seconds,
        granted_expires_str=granted_str,
    )


def analyze_inbound_subscribe_envelope(
    soap_text: str, *, max_grant_seconds: float
) -> InboundSubscribeAnalysis:
    """Validate inbound ``Subscribe`` XML for a minimal Push + optional Action filter profile.

    Args:
        soap_text: Full SOAP 1.2 envelope text.
        max_grant_seconds: Upper bound for granted lease duration (wall-clock seconds).

    Returns:
        Analysis including either fault fields or granted lease duration and ``wse:Expires`` text.
    """
    try:
        root = ET.fromstring(soap_text)
    except ET.ParseError:
        return _fault(0.0, "PT0S", "InvalidMessage", "SOAP envelope is not well-formed XML")

    body = root.find(f".//{{{NS_SOAP}}}Body")
    if body is None:
        return _fault(0.0, "PT0S", "InvalidMessage", "Missing SOAP Body")

    subscribe_el = None
    for child in body:
        tag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
        if tag == "Subscribe":
            subscribe_el = child
            break
    if subscribe_el is None:
        return _fault(0.0, "PT0S", "InvalidMessage", "Missing wse:Subscribe in SOAP Body")

    delivery = None
    for child in subscribe_el:
        tag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
        if tag == "Delivery":
            delivery = child
            break
    if delivery is None:
        return _fault(0.0, "PT0S", "InvalidMessage", "Missing wse:Delivery")

    mode = (delivery.get("Mode") or delivery.get("mode") or "").strip()
    if mode != WSE_DELIVERY_MODE_PUSH:
        return _fault(
            0.0,
            "PT0S",
            "DeliveryModeRequestedUnavailable",
            "Only Push delivery mode is supported for inbound Subscribe",
        )

    notify_addr: str | None = None
    for child in delivery:
        tag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
        if tag != "NotifyTo":
            continue
        for sub in child:
            st = sub.tag.split("}", 1)[-1] if "}" in sub.tag else sub.tag
            if st == "Address" and (sub.text or "").strip():
                notify_addr = (sub.text or "").strip()
                break
        if notify_addr:
            break
    if not notify_addr:
        return _fault(0.0, "PT0S", "InvalidMessage", "Missing or empty wse:NotifyTo/wsa:Address")

    filter_elems = [
        c for c in subscribe_el if (c.tag.split("}", 1)[-1] if "}" in c.tag else c.tag) == "Filter"
    ]
    if filter_elems:
        fe = filter_elems[0]
        dialect = (fe.get("Dialect") or fe.get("dialect") or "").strip()
        action_text = (fe.text or "").strip()
        if dialect != FILTER_DIALECT_DEVPROF_ACTION or action_text not in _SUPPORTED_FILTER_ACTIONS:
            return _fault(
                0.0,
                "PT0S",
                "FilteringNotSupported",
                "Unsupported wse:Filter dialect or action for this event source",
            )

    expires_el = None
    for child in subscribe_el:
        tag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
        if tag == "Expires":
            expires_el = child
            break
    raw_expires = (expires_el.text or "").strip() if expires_el is not None else ""
    if raw_expires:
        try:
            requested = parse_iso8601_duration_to_seconds(raw_expires)
        except ValueError:
            return _fault(
                0.0,
                "PT0S",
                "UnacceptableInitialTerminationTime",
                f"Could not parse requested wse:Expires duration: {raw_expires!r}",
            )
    else:
        requested = parse_iso8601_duration_to_seconds("PT1H")

    granted = min(max(requested, 1.0), max(1.0, max_grant_seconds))
    granted_str = _format_iso8601_duration_from_seconds(granted)
    return _ok(granted, granted_str)


def extract_renew_or_getstatus_expires_request(soap_text: str) -> str | None:
    """Return raw ``wse:Expires`` text from a Renew body, if present."""
    m = EXPIRES_PATTERN.search(soap_text)
    return m.group(1).strip() if m else None


def _format_iso8601_duration_from_seconds(sec: float) -> str:
    """Format a non-negative duration as ``xs:duration`` (``PT…`` form)."""
    if sec <= 0:
        return "PT0S"
    total = int(round(sec))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}H")
    if m:
        parts.append(f"{m}M")
    if s or not parts:
        parts.append(f"{s}S")
    return "PT" + "".join(parts)

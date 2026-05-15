"""Parse inbound WS-Eventing ``SubscriptionEnd`` notifications (sink role)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

__all__ = ["ParsedInboundSubscriptionEnd", "parse_inbound_subscription_end"]


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


@dataclass(frozen=True)
class ParsedInboundSubscriptionEnd:
    """Logical fields from a ``wse:SubscriptionEnd`` body."""

    subscription_identifier: str | None
    status_uri: str | None
    reasons: tuple[str, ...]


def parse_inbound_subscription_end(soap_text: str) -> ParsedInboundSubscriptionEnd | None:
    """Parse ``wse:SubscriptionEnd`` under ``soap:Body``; return ``None`` if missing or malformed."""
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
    end_el: ET.Element | None = None
    for ch in body:
        if _local_name(ch.tag) == "SubscriptionEnd":
            end_el = ch
            break
    if end_el is None:
        return None

    mgr_el = _child_by_local(end_el, "SubscriptionManager")
    id_el = _child_by_local(mgr_el, "Identifier") if mgr_el is not None else None
    sub_id = _text_direct(id_el) or None

    status_el = _child_by_local(end_el, "Status")
    status_uri = _text_direct(status_el) or None

    reasons: list[str] = []
    for ch in end_el:
        if _local_name(ch.tag) == "Reason" and (ch.text or "").strip():
            reasons.append((ch.text or "").strip())

    return ParsedInboundSubscriptionEnd(
        subscription_identifier=sub_id,
        status_uri=status_uri,
        reasons=tuple(reasons),
    )

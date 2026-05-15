"""WS-Discovery SOAP helpers: extractors for inbound ProbeMatch / ResolveMatch."""

from __future__ import annotations

import re

from app.soap.xmlutil import wsa_header_first_string

XADDR_PATTERN = re.compile(r"<(?:[A-Za-z0-9_]+:)?XAddrs>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?XAddrs>")


def extract_message_id_strict(text: str) -> str | None:
    """Extract first ``wsa:MessageID`` or None."""
    return wsa_header_first_string(text, "MessageID")


def extract_message_id_or_unknown(text: str) -> str:
    """Extract first ``wsa:MessageID``; default ``uuid:unknown`` when missing."""
    mid = wsa_header_first_string(text, "MessageID")
    return mid if mid else "uuid:unknown"


def extract_action(text: str) -> str | None:
    """Extract WS-Addressing Action value from SOAP payload."""
    return wsa_header_first_string(text, "Action")


def extract_relates_to(text: str) -> str | None:
    """Extract first ``wsa:RelatesTo`` value."""
    return wsa_header_first_string(text, "RelatesTo")


def extract_xaddrs(text: str) -> list[str]:
    """Extract space-separated XAddrs list."""
    match = XADDR_PATTERN.search(text)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split() if part.strip()]

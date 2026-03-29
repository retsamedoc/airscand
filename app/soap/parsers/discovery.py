"""WS-Discovery SOAP helpers: extractors for inbound ProbeMatch / ResolveMatch."""

from __future__ import annotations

import re

from app.soap.addressing import (
    ACTION_PATTERN,
    MESSAGE_ID_PATTERN,
    RELATES_TO_PATTERN,
)

XADDR_PATTERN = re.compile(r"<(?:[A-Za-z0-9_]+:)?XAddrs>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?XAddrs>")


def extract_message_id_strict(text: str) -> str | None:
    """Extract first ``wsa:MessageID`` or None."""
    match = MESSAGE_ID_PATTERN.search(text)
    return match.group(1).strip() if match else None


def extract_message_id_or_unknown(text: str) -> str:
    """Extract first ``wsa:MessageID``; default ``uuid:unknown`` when missing."""
    match = MESSAGE_ID_PATTERN.search(text)
    if not match:
        return "uuid:unknown"
    return match.group(1).strip()


def extract_action(text: str) -> str | None:
    """Extract WS-Addressing Action value from SOAP payload."""
    match = ACTION_PATTERN.search(text)
    return match.group(1).strip() if match else None


def extract_relates_to(text: str) -> str | None:
    """Extract first ``wsa:RelatesTo`` value."""
    match = RELATES_TO_PATTERN.search(text)
    return match.group(1).strip() if match else None


def extract_xaddrs(text: str) -> list[str]:
    """Extract space-separated XAddrs list."""
    match = XADDR_PATTERN.search(text)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split() if part.strip()]

"""WS-Addressing header extraction and message identifiers."""

from __future__ import annotations

import re
import uuid

MESSAGE_ID_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?MessageID>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?MessageID>"
)
ACTION_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Action>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Action>"
)
RELATES_TO_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?RelatesTo>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?RelatesTo>"
)
WSA_MESSAGE_ID_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?MessageID>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?MessageID>"
)
WSA_ACTION_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Action>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Action>"
)


def new_message_id() -> str:
    """Generate WS-Addressing message identifier."""
    return f"urn:uuid:{uuid.uuid4()}"


def soap_action_short(action: str | None) -> str | None:
    """Last path segment of a SOAP Action URI for compact logs."""
    if not action:
        return None
    return action.rstrip("/").rsplit("/", 1)[-1]


def extract_wsa_action(payload: str) -> str | None:
    """Return first WS-Addressing Action URI in a SOAP envelope."""
    match = WSA_ACTION_PATTERN.search(payload)
    return match.group(1).strip() if match else None


def extract_message_id_optional(text: str) -> str | None:
    """Extract first ``wsa:MessageID`` value, or None if absent."""
    match = MESSAGE_ID_PATTERN.search(text)
    return match.group(1).strip() if match else None


def extract_action(text: str) -> str | None:
    """Extract WS-Addressing Action value from SOAP payload."""
    match = ACTION_PATTERN.search(text)
    return match.group(1).strip() if match else None


def extract_relates_to(text: str) -> str | None:
    """Extract first ``wsa:RelatesTo`` value."""
    match = RELATES_TO_PATTERN.search(text)
    return match.group(1).strip() if match else None

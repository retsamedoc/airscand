"""WS-Addressing header extraction and message identifiers."""

from __future__ import annotations

import uuid

from app.soap.xmlutil import wsa_header_first_string


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
    return wsa_header_first_string(payload, "Action")


def extract_message_id_optional(text: str) -> str | None:
    """Extract first ``wsa:MessageID`` value, or None if absent."""
    return wsa_header_first_string(text, "MessageID")


def extract_action(text: str) -> str | None:
    """Extract WS-Addressing Action value from SOAP payload."""
    return wsa_header_first_string(text, "Action")


def extract_relates_to(text: str) -> str | None:
    """Extract first ``wsa:RelatesTo`` value."""
    return wsa_header_first_string(text, "RelatesTo")

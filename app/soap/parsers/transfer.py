"""WS-Transfer Get preflight (subscribe URL discovery)."""

from __future__ import annotations

import re

from app.soap.envelope import build_outbound_client_envelope
from app.soap.namespaces import ACTION_GET, NS_WST

URI_TEXT_PATTERN = re.compile(r"https?://[A-Za-z0-9._:/-]+")


def build_get_request(
    *,
    to_url: str,
    message_id: str | None = None,
    from_address: str | None = None,
) -> tuple[str, str]:
    """Build WS-Transfer Get SOAP envelope."""
    return build_outbound_client_envelope(
        xmlns_extra={"wst": NS_WST},
        action=ACTION_GET,
        to_url=to_url,
        body_inner_xml="",
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id="",
    )


def parse_get_response(text: str) -> dict[str, str | None]:
    """Extract candidate subscribe endpoint from WS-Transfer response."""
    values = URI_TEXT_PATTERN.findall(text)
    subscribe_to = next((value for value in values if "/WDP/SCAN" in value), None)
    if not subscribe_to:
        subscribe_to = next((value for value in values if "WSDScanner" in value), None)
    return {"suggested_subscribe_to_url": subscribe_to}


# Re-export for resolve_wdp_scan_url (scan chain)
def first_http_uri_in_text(text: str) -> str | None:
    """Return first http(s) URI match or None."""
    m = URI_TEXT_PATTERN.search(text)
    return m.group(0) if m else None

"""WS-Eventing response parsing helpers."""

from __future__ import annotations

import re
from typing import Any

IDENTIFIER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Identifier>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Identifier>"
)
EXPIRES_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Expires>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?Expires>"
)
DESTINATION_TOKEN_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?DestinationToken>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?DestinationToken>"
)
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
SUBSCRIPTION_MANAGER_INNER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?SubscriptionManager\b[^>]*>(.*?)</(?:[A-Za-z0-9_]+:)?SubscriptionManager>",
    re.DOTALL | re.IGNORECASE,
)

def effective_subscription_identifier_for_unsubscribe(
    subscription_identifier: str,
    reference_parameters_xml: str | None,
) -> str | None:
    """Resolve subscription id for Unsubscribe ``wse:Identifier`` header."""
    ref = (reference_parameters_xml or "").strip()
    if ref:
        m = IDENTIFIER_PATTERN.search(ref)
        if m:
            return m.group(1).strip()
        loose = re.search(
            r"<(?:[A-Za-z0-9_]+:)?Identifier>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?Identifier>",
            ref,
            re.DOTALL | re.IGNORECASE,
        )
        if loose:
            return loose.group(1).strip()
    sub = (subscription_identifier or "").strip()
    return sub if sub else None


def extract_subscribe_destination_tokens_by_client_context(text: str) -> dict[str, str]:
    """Parse all ``DestinationResponse`` entries: ``ClientContext`` -> ``DestinationToken``."""
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
    """Extract first ``DestinationToken`` from ``DestinationResponses``."""
    mapping = extract_subscribe_destination_tokens_by_client_context(text)
    if mapping:
        return next(iter(mapping.values()))
    block = DESTINATION_RESPONSES_BLOCK_PATTERN.search(text)
    if not block:
        return None
    match = DESTINATION_TOKEN_PATTERN.search(block.group(0))
    return match.group(1).strip() if match else None


def extract_subscription_manager_epr(text: str) -> tuple[str | None, str | None]:
    """Extract Subscription Manager EPR ``Address`` and optional ``ReferenceParameters`` XML."""
    m = SUBSCRIPTION_MANAGER_INNER_PATTERN.search(text)
    if not m:
        return None, None
    inner = m.group(1)
    addr_m = re.search(
        r"<(?:[A-Za-z0-9_]+:)?Address>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?Address>",
        inner,
        re.DOTALL | re.IGNORECASE,
    )
    addr = addr_m.group(1).strip() if addr_m else None
    ref_m = re.search(
        r"<(?:[A-Za-z0-9_]+:)?ReferenceParameters\b[^>]*>.*?</(?:[A-Za-z0-9_]+:)?ReferenceParameters>",
        inner,
        re.DOTALL | re.IGNORECASE,
    )
    ref_xml = ref_m.group(0).strip() if ref_m else None
    return addr, ref_xml


def extract_subscription_manager_url(text: str) -> str | None:
    """Extract ``wsa:Address`` inside ``wse:SubscriptionManager`` from SubscribeResponse."""
    addr, _ = extract_subscription_manager_epr(text)
    return addr


def parse_subscribe_response(text: str) -> dict[str, Any]:
    """Extract subscription details from SOAP response body."""
    identifier_match = IDENTIFIER_PATTERN.search(text)
    expires_match = EXPIRES_PATTERN.search(text)
    tokens_map = extract_subscribe_destination_tokens_by_client_context(text)
    subscribe_destination_token = extract_subscribe_destination_token(text)
    mgr_addr, mgr_ref = extract_subscription_manager_epr(text)
    return {
        "identifier": identifier_match.group(1).strip() if identifier_match else None,
        "expires": expires_match.group(1).strip() if expires_match else None,
        "subscribe_destination_token": subscribe_destination_token,
        "subscribe_destination_tokens": tokens_map if tokens_map else None,
        "subscription_manager_url": mgr_addr,
        "subscription_manager_address": mgr_addr,
        "subscription_manager_reference_parameters_xml": mgr_ref,
    }

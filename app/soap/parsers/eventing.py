"""WS-Eventing response parsing helpers."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from app.soap.namespaces import NS_WSE
from app.soap.xmlutil import (
    first_child_by_local,
    local_name,
    parse_soap_envelope,
    parse_xml_fragment_with_default_ns,
    serialize_element_pretty_ns,
    soap_body,
)

_SECONDS_PER_DAY = 86400.0
_SECONDS_PER_WEEK = 7 * _SECONDS_PER_DAY
# Calendar approximations for Y/M when scanners emit full ISO date components.
_SECONDS_PER_MONTH = 30 * _SECONDS_PER_DAY
_SECONDS_PER_YEAR = 365.25 * _SECONDS_PER_DAY


def _element_text_shallow(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    t = (el.text or "").strip()
    if t:
        return t
    joined = "".join(el.itertext()).strip()
    return joined if joined else None


def _find_body_child(body: ET.Element, response_local: str) -> ET.Element | None:
    for ch in body:
        if local_name(ch.tag) == response_local:
            return ch
    return None


def _subscribe_response_from_document(text: str) -> ET.Element | None:
    env = parse_soap_envelope(text)
    if env is None:
        return None
    body = soap_body(env)
    if body is None:
        return None
    return _find_body_child(body, "SubscribeResponse")


def _renew_response_from_document(text: str) -> ET.Element | None:
    env = parse_soap_envelope(text)
    if env is None:
        return None
    body = soap_body(env)
    if body is None:
        return None
    return _find_body_child(body, "RenewResponse")


def _get_status_response_from_document(text: str) -> ET.Element | None:
    env = parse_soap_envelope(text)
    if env is None:
        return None
    body = soap_body(env)
    if body is None:
        return None
    return _find_body_child(body, "GetStatusResponse")


def _subscribe_response_direct_identifier(sub_resp: ET.Element) -> str | None:
    """First ``Identifier`` that is a direct child of ``SubscribeResponse`` only."""
    for ch in sub_resp:
        if local_name(ch.tag) == "Identifier":
            got = _element_text_shallow(ch)
            if got:
                return got
    return None


def _subscribe_response_direct_expires(sub_resp: ET.Element) -> str | None:
    for ch in sub_resp:
        if local_name(ch.tag) == "Expires":
            got = _element_text_shallow(ch)
            if got:
                return got
    return None


def _first_subscription_manager(sub_resp: ET.Element) -> ET.Element | None:
    return first_child_by_local(sub_resp, "SubscriptionManager")


def _subscription_manager_epr_parts(
    mgr: ET.Element,
) -> tuple[str | None, str | None]:
    addr_el = first_child_by_local(mgr, "Address")
    addr = _element_text_shallow(addr_el) if addr_el is not None else None
    ref_el = first_child_by_local(mgr, "ReferenceParameters")
    ref_xml = serialize_element_pretty_ns(ref_el).strip() if ref_el is not None else None
    return addr, ref_xml


def _destination_tokens_map(sub_resp: ET.Element) -> dict[str, str]:
    block = first_child_by_local(sub_resp, "DestinationResponses")
    if block is None:
        return {}
    out: dict[str, str] = {}
    for dr in block:
        if local_name(dr.tag) != "DestinationResponse":
            continue
        cc_el = first_child_by_local(dr, "ClientContext")
        tok_el = first_child_by_local(dr, "DestinationToken")
        key = _element_text_shallow(cc_el) or ""
        val = _element_text_shallow(tok_el) or ""
        if key and val and key not in out:
            out[key] = val
    return out


def subscription_identifier_from_reference_parameters_xml(ref_xml: str) -> str | None:
    """Resolve ``wse:Identifier`` (or first ``Identifier``) inside reference parameters."""
    root = parse_xml_fragment_with_default_ns(ref_xml)
    if root is None:
        return None
    if local_name(root.tag) == "Identifier":
        return _element_text_shallow(root)
    rp = (
        root
        if local_name(root.tag) == "ReferenceParameters"
        else first_child_by_local(root, "ReferenceParameters")
    )
    if rp is not None:
        for ch in rp:
            if ch.tag == f"{{{NS_WSE}}}Identifier":
                got = _element_text_shallow(ch)
                if got:
                    return got
        for ch in rp:
            if local_name(ch.tag) == "Identifier":
                got = _element_text_shallow(ch)
                if got:
                    return got
        return None
    for el in root.iter():
        if el.tag == f"{{{NS_WSE}}}Identifier":
            got = _element_text_shallow(el)
            if got:
                return got
    return None


def effective_subscription_identifier_for_unsubscribe(
    subscription_identifier: str,
    reference_parameters_xml: str | None,
) -> str | None:
    """Resolve subscription id for Unsubscribe ``wse:Identifier`` header."""
    ref = (reference_parameters_xml or "").strip()
    if ref:
        parsed = subscription_identifier_from_reference_parameters_xml(ref)
        if parsed:
            return parsed
    sub = (subscription_identifier or "").strip()
    return sub if sub else None


def extract_subscribe_destination_tokens_by_client_context(text: str) -> dict[str, str]:
    """Parse all ``DestinationResponse`` entries: ``ClientContext`` -> ``DestinationToken``."""
    sub_resp = _subscribe_response_from_document(text)
    if sub_resp is None:
        return {}
    return _destination_tokens_map(sub_resp)


def extract_subscribe_destination_token(text: str) -> str | None:
    """Extract first ``DestinationToken`` from ``DestinationResponses``."""
    mapping = extract_subscribe_destination_tokens_by_client_context(text)
    if mapping:
        return next(iter(mapping.values()))
    sub_resp = _subscribe_response_from_document(text)
    if sub_resp is None:
        return None
    block = first_child_by_local(sub_resp, "DestinationResponses")
    if block is None:
        return None
    for dr in block:
        if local_name(dr.tag) != "DestinationResponse":
            continue
        tok_el = first_child_by_local(dr, "DestinationToken")
        tok = _element_text_shallow(tok_el)
        if tok:
            return tok
    return None


def extract_subscription_manager_epr(text: str) -> tuple[str | None, str | None]:
    """Extract Subscription Manager EPR ``Address`` and optional ``ReferenceParameters`` XML."""
    sub_resp = _subscribe_response_from_document(text)
    if sub_resp is None:
        return None, None
    mgr = _first_subscription_manager(sub_resp)
    if mgr is None:
        return None, None
    return _subscription_manager_epr_parts(mgr)


def extract_subscription_manager_url(text: str) -> str | None:
    """Extract ``wsa:Address`` inside ``wse:SubscriptionManager`` from SubscribeResponse."""
    addr, _ = extract_subscription_manager_epr(text)
    return addr


def parse_subscribe_response(text: str) -> dict[str, Any]:
    """Extract subscription details from SOAP response body."""
    sub_resp = _subscribe_response_from_document(text)
    if sub_resp is None:
        return {
            "identifier": None,
            "expires": None,
            "subscribe_destination_token": None,
            "subscribe_destination_tokens": None,
            "subscription_manager_url": None,
            "subscription_manager_address": None,
            "subscription_manager_reference_parameters_xml": None,
        }
    identifier = _subscribe_response_direct_identifier(sub_resp)
    expires = _subscribe_response_direct_expires(sub_resp)
    tokens_map = _destination_tokens_map(sub_resp)
    subscribe_destination_token = extract_subscribe_destination_token(text)
    mgr = _first_subscription_manager(sub_resp)
    mgr_addr: str | None = None
    mgr_ref: str | None = None
    if mgr is not None:
        mgr_addr, mgr_ref = _subscription_manager_epr_parts(mgr)
    return {
        "identifier": identifier,
        "expires": expires,
        "subscribe_destination_token": subscribe_destination_token,
        "subscribe_destination_tokens": tokens_map if tokens_map else None,
        "subscription_manager_url": mgr_addr,
        "subscription_manager_address": mgr_addr,
        "subscription_manager_reference_parameters_xml": mgr_ref,
    }


def parse_iso8601_duration_to_seconds(expires: str) -> float:
    """Parse an XML ``xs:duration`` / ISO 8601 duration string to seconds.

    Supports common scanner forms such as ``PT1H``, ``PT45M``, ``P1D``, and
    ``P0Y0M0DT30H0M0S``. Year and month components use calendar approximations.

    Args:
        expires: Duration string, typically from ``wse:Expires``.

    Returns:
        Non-negative duration in seconds.

    Raises:
        ValueError: If the string is empty or cannot be parsed as a duration.
    """
    text = expires.strip()
    if not text:
        msg = "empty duration string"
        raise ValueError(msg)
    if text[0] not in "Pp":
        msg = f"not an ISO 8601 duration: {expires!r}"
        raise ValueError(msg)
    rest = text[1:]
    if rest.startswith("T") or rest.startswith("t"):
        date_part, time_part = "", rest[1:]
    elif "T" in rest or "t" in rest:
        lower = rest.lower()
        idx = lower.index("t")
        date_part, time_part = rest[:idx], rest[idx + 1 :]
    else:
        date_part, time_part = rest, ""

    total = 0.0
    for match in re.finditer(r"(\d+(?:\.\d+)?)([YMWDymwd])", date_part):
        value = float(match.group(1))
        unit = match.group(2).upper()
        if unit == "Y":
            total += value * _SECONDS_PER_YEAR
        elif unit == "M":
            total += value * _SECONDS_PER_MONTH
        elif unit == "W":
            total += value * _SECONDS_PER_WEEK
        elif unit == "D":
            total += value * _SECONDS_PER_DAY
    for match in re.finditer(r"(\d+(?:\.\d+)?)([HMShms])", time_part):
        value = float(match.group(1))
        unit = match.group(2).upper()
        if unit == "H":
            total += value * 3600.0
        elif unit == "M":
            total += value * 60.0
        elif unit == "S":
            total += value

    if total < 0:
        msg = f"negative duration: {expires!r}"
        raise ValueError(msg)
    return total


def parse_renew_response(text: str) -> dict[str, Any]:
    """Extract granted expiration from a WS-Eventing RenewResponse body."""
    renew = _renew_response_from_document(text)
    expires: str | None = None
    if renew is not None:
        for ch in renew:
            if local_name(ch.tag) == "Expires":
                expires = _element_text_shallow(ch)
                if expires:
                    break
    return {
        "expires": expires,
    }


def parse_get_status_response(text: str) -> dict[str, Any]:
    """Extract current expiration from a WS-Eventing GetStatusResponse body."""
    status_resp = _get_status_response_from_document(text)
    expires: str | None = None
    if status_resp is not None:
        for ch in status_resp:
            if local_name(ch.tag) == "Expires":
                expires = _element_text_shallow(ch)
                if expires:
                    break
    return {
        "expires": expires,
    }

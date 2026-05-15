"""Namespace-aware SOAP helpers (ElementTree).

Used for WS-Eventing responses, WS-Addressing headers, and SOAP faults so prefix
choices and benign reordering do not change extracted fields.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.soap.namespaces import NS_SOAP, NS_WSA, NS_WSE

_NS_ET_REGISTERED = False


def ensure_et_namespace_prefixes() -> None:
    """Register common URIs so ``ElementTree.tostring`` uses stable prefixes."""
    global _NS_ET_REGISTERED
    if _NS_ET_REGISTERED:
        return
    ET.register_namespace("soap", NS_SOAP)
    ET.register_namespace("wsa", NS_WSA)
    ET.register_namespace("wse", NS_WSE)
    ET.register_namespace("wsman", "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd")
    ET.register_namespace("wscn", "http://schemas.microsoft.com/windows/2006/01/wdp/scan")
    ET.register_namespace("sca", "http://schemas.microsoft.com/windows/2006/08/wdp/scan")
    _NS_ET_REGISTERED = True


def local_name(tag: str) -> str:
    """Return XML local name, stripping ``{namespace}`` if present."""
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def child_by_qname(parent: ET.Element, uri: str, name: str) -> ET.Element | None:
    """First direct child matching ``{uri}name``."""
    want = f"{{{uri}}}{name}"
    for ch in parent:
        if ch.tag == want:
            return ch
    return None


def first_child_by_local(parent: ET.Element, name: str) -> ET.Element | None:
    """First direct child whose local name matches (any namespace)."""
    for ch in parent:
        if local_name(ch.tag) == name:
            return ch
    return None


def parse_xml_fragment(text: str) -> ET.Element | None:
    """Parse XML from a string; return root element or ``None`` on failure."""
    raw = text.strip()
    if not raw:
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def parse_xml_fragment_with_default_ns(text: str) -> ET.Element | None:
    """Parse a fragment that may lack namespace declarations (e.g. saved EPR XML)."""
    root = parse_xml_fragment(text)
    if root is not None:
        return root
    raw = text.strip()
    if not raw:
        return None
    wrapped = (
        f'<airscand:wrap xmlns:airscand="urn:airscand:xml-wrap" '
        f'xmlns:wsa="{NS_WSA}" xmlns:wse="{NS_WSE}" '
        f'xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">'
        f"{raw}</airscand:wrap>"
    )
    try:
        wrap = ET.fromstring(wrapped)
    except ET.ParseError:
        return None
    return wrap[0] if len(wrap) else None


def register_common_namespaces() -> dict[str, str]:
    """Namespace prefix map for ElementTree iteration (SOAP 1.2 + WS-A 2004/08)."""
    return {
        "soap": NS_SOAP,
        "wsa": NS_WSA,
        "wse": NS_WSE,
    }


def parse_soap_envelope(text: str) -> ET.Element | None:
    """Parse a SOAP envelope document."""
    return parse_xml_fragment(text)


def soap_header(envelope: ET.Element) -> ET.Element | None:
    """Return the ``Header`` child of ``Envelope``."""
    h = child_by_qname(envelope, NS_SOAP, "Header")
    return h if h is not None else first_child_by_local(envelope, "Header")


def soap_body(envelope: ET.Element) -> ET.Element | None:
    """Return the ``Body`` child of ``Envelope``."""
    b = child_by_qname(envelope, NS_SOAP, "Body")
    return b if b is not None else first_child_by_local(envelope, "Body")


def wsa_header_first_string(soap_text: str, header_local: str) -> str | None:
    """First ``wsa:{header_local}`` text in the SOAP header (prefix-independent)."""
    env = parse_soap_envelope(soap_text)
    if env is None:
        return None
    hdr = soap_header(env)
    if hdr is None:
        return None
    el = child_by_qname(hdr, NS_WSA, header_local)
    if el is None:
        el = first_child_by_local(hdr, header_local)
    if el is None:
        return None
    t = (el.text or "").strip()
    return t if t else None


def extract_wse_identifier_from_soap_header(soap_text: str) -> str | None:
    """First subscription ``Identifier`` in the SOAP ``Header`` (WS-Eventing management).

    Prefer ``wse:Identifier``; otherwise the first header child named ``Identifier``.
    """
    env = parse_soap_envelope(soap_text)
    if env is None:
        return None
    hdr = soap_header(env)
    if hdr is None:
        return None
    el = child_by_qname(hdr, NS_WSE, "Identifier")
    if el is not None:
        t = (el.text or "").strip()
        if t:
            return t
    for ch in hdr:
        if local_name(ch.tag) == "Identifier":
            t = (ch.text or "").strip()
            if t:
                return t
    return None


def extract_wsa_to_optional(soap_text: str) -> str | None:
    """Return first ``wsa:To`` in the SOAP header, if any."""
    return wsa_header_first_string(soap_text, "To")


def serialize_element_pretty_ns(el: ET.Element) -> str:
    """Serialize subtree with stable common prefixes for tests and logs."""
    ensure_et_namespace_prefixes()
    return ET.tostring(el, encoding="unicode")

"""Tests for Phase-2 XML utility stubs."""

from __future__ import annotations

from app.soap import xmlutil
from app.soap.namespaces import NS_SOAP, NS_WSA


def test_parse_xml_fragment_valid() -> None:
    """Valid XML returns an Element."""
    root = xmlutil.parse_xml_fragment(
        f'<soap:Envelope xmlns:soap="{NS_SOAP}"><soap:Body/></soap:Envelope>'
    )
    assert root is not None
    assert "Envelope" in root.tag


def test_parse_xml_fragment_invalid() -> None:
    """Malformed XML returns None."""
    assert xmlutil.parse_xml_fragment("not xml") is None


def test_register_common_namespaces() -> None:
    """Prefix map includes soap and wsa URIs."""
    ns = xmlutil.register_common_namespaces()
    assert ns["soap"] == NS_SOAP
    assert ns["wsa"] == NS_WSA

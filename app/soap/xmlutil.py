"""Phase-2 hooks: namespace-aware XML helpers (ElementTree).

Use for outbound header validation, RelatesTo checks, and fault parsing with regex
fallback. Prefer keeping device-facing body XML byte-stable; expand coverage only
where audits require it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def parse_xml_fragment(text: str) -> ET.Element | None:
    """Parse XML from a string; return root element or ``None`` on failure."""
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


def register_common_namespaces() -> dict[str, str]:
    """Namespace prefix map for ElementTree iteration (SOAP 1.2 + WS-A 2004/08)."""
    from app.soap.namespaces import NS_SOAP, NS_WSA

    return {
        "soap": NS_SOAP,
        "wsa": NS_WSA,
    }

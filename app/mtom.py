"""Parse MTOM multipart/related SOAP responses (e.g. WS-Scan RetrieveImage)."""

from __future__ import annotations

import re
from email import message_from_bytes
from email.policy import default as email_policy

__all__ = [
    "extract_boundary_from_content_type",
    "extract_xop_include_cid",
    "normalize_cid",
    "parse_multipart_related_parts",
    "parse_retrieve_image_mtom",
]

XOP_INCLUDE_HREF_PATTERN = re.compile(
    r"<[^>]*:Include\b[^>]*\bhref\s*=\s*[\"']cid:([^\"']+)[\"']",
    re.IGNORECASE | re.DOTALL,
)


def extract_boundary_from_content_type(content_type: str) -> str | None:
    """Return the multipart ``boundary`` parameter (unquoted)."""
    for segment in content_type.split(";"):
        segment = segment.strip()
        if not segment.lower().startswith("boundary="):
            continue
        value = segment.split("=", 1)[1].strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            return value[1:-1]
        return value
    return None


def normalize_cid(reference: str) -> str:
    """Normalize ``cid:…``, ``<…>``, and surrounding whitespace for comparison."""
    ref = reference.strip()
    lower = ref.lower()
    if lower.startswith("cid:"):
        ref = ref[4:]
    ref = ref.strip()
    if ref.startswith("<") and ref.endswith(">"):
        ref = ref[1:-1]
    return ref.strip()


def extract_xop_include_cid(soap_xml: str) -> str | None:
    """Return the cid token from the first ``xop:Include`` (or equivalent) ``href``."""
    match = XOP_INCLUDE_HREF_PATTERN.search(soap_xml)
    if not match:
        return None
    return match.group(1).strip()


def parse_multipart_related_parts(
    body: bytes, content_type_header: str
) -> list[tuple[dict[str, str], bytes]]:
    """Split a multipart/related body using the outer ``Content-Type`` (with boundary)."""
    raw = (
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: "
        + content_type_header.encode("ascii", errors="replace")
        + b"\r\n\r\n"
        + body
    )
    msg = message_from_bytes(raw, policy=email_policy)
    parts: list[tuple[dict[str, str], bytes]] = []
    if not msg.is_multipart():
        return parts
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        hdrs = {str(k): str(v) for k, v in part.items()}
        payload = part.get_payload(decode=True)
        if payload is None:
            pl = part.get_payload()
            payload = pl.encode("utf-8") if isinstance(pl, str) else b""
        elif isinstance(payload, str):
            payload = payload.encode("utf-8")
        parts.append((hdrs, payload))
    return parts


def parse_retrieve_image_mtom(
    body: bytes,
    response_content_type: str | None,
) -> tuple[str, bytes | None, str | None]:
    """Parse RetrieveImage HTTP body.

    Returns ``(soap_xml_text, image_bytes_or_none, image_part_content_type_or_none)``.
    For non-multipart responses, returns ``(decoded_soap_text, None, None)``.
    """
    ct = (response_content_type or "").lower()
    if "multipart/related" not in ct:
        soap_text = body.decode("utf-8", errors="replace")
        return soap_text, None, None

    outer = response_content_type or ""
    if not extract_boundary_from_content_type(outer):
        soap_text = body.decode("utf-8", errors="replace")
        return soap_text, None, None

    part_list = parse_multipart_related_parts(body, outer.strip())
    if not part_list:
        soap_text = body.decode("utf-8", errors="replace")
        return soap_text, None, None

    soap_xml: str | None = None
    for hdrs, payload in part_list:
        ctype = (hdrs.get("Content-Type") or hdrs.get("Content-type") or "").lower()
        if "xml" in ctype or payload.lstrip().startswith(b"<?xml") or payload.lstrip().startswith(b"<soap:"):
            soap_xml = payload.decode("utf-8", errors="replace")
            break

    if soap_xml is None:
        _, first_payload = part_list[0]
        soap_xml = first_payload.decode("utf-8", errors="replace")

    cid_ref = extract_xop_include_cid(soap_xml)
    if not cid_ref:
        return soap_xml, None, None

    target = normalize_cid(f"cid:{cid_ref}")
    image_bytes: bytes | None = None
    image_ct: str | None = None
    for hdrs, payload in part_list:
        raw_cid = hdrs.get("Content-ID") or hdrs.get("Content-Id") or ""
        if not raw_cid:
            continue
        if normalize_cid(raw_cid) != target:
            continue
        image_bytes = payload
        image_ct = hdrs.get("Content-Type") or hdrs.get("Content-type")
        break

    return soap_xml, image_bytes, image_ct

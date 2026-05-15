"""Parse MTOM multipart/related SOAP responses (e.g. WS-Scan RetrieveImage)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import message_from_bytes
from email.policy import default as email_policy

__all__ = [
    "MtomPayloadIntegrityReport",
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


@dataclass
class MtomPayloadIntegrityReport:
    """Outcome of structural checks on a RetrieveImage HTTP body (MTOM or SOAP-only).

    Why: scanners occasionally truncate chunked MTOM streams or omit binary parts; treating
    those as success would persist corrupt scans. This report drives explicit failure instead
    of silent data loss.
    """

    ok: bool
    reason_code: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


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


def _multipart_has_closing_delimiter(body: bytes, boundary: str) -> bool:
    """Return True when the raw body ends with a closing multipart delimiter for ``boundary``."""
    try:
        b = boundary.encode("ascii")
    except UnicodeEncodeError:
        return False
    candidates = (
        b"\r\n--" + b + b"--\r\n",
        b"\r\n--" + b + b"--\n",
        b"\n--" + b + b"--\n",
        b"\n--" + b + b"--\r\n",
        b"--" + b + b"--\r\n",
        b"--" + b + b"--\n",
        b"--" + b + b"--",
    )
    return any(body.endswith(s) for s in candidates)


def _parse_positive_int_header(value: str) -> int | None:
    stripped = value.strip()
    if not stripped.isdigit():
        return None
    return int(stripped)


def _mime_main_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower()


def _binary_magic_matches_declared_mime(content_type: str | None, data: bytes) -> bool:
    """Return False when a declared image MIME clearly disagrees with leading magic bytes."""
    if not data:
        return False
    main = _mime_main_type(content_type)
    if main in (None, "", "application/octet-stream", "binary/octet-stream"):
        return True
    if main in ("image/jpeg", "image/jpg", "image/pjpeg"):
        return data.startswith(b"\xff\xd8")
    if main == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\x89PNG\n")
    if main in ("image/tiff", "image/tif", "image/x-tiff"):
        return data.startswith(b"II*\x00") or data.startswith(b"MM\x00*")
    if main == "application/pdf":
        return data.startswith(b"%PDF")
    return True


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
) -> tuple[str, bytes | None, str | None, MtomPayloadIntegrityReport]:
    """Parse RetrieveImage HTTP body.

    Returns ``(soap_xml_text, image_bytes_or_none, image_part_content_type_or_none, integrity)``.
    For non-multipart responses, returns ``(decoded_soap_text, None, None, integrity)`` where
    integrity is OK (no MTOM binary contract applies).

    Integrity checks (multipart): closing boundary present, per-part ``Content-Length`` when
    present matches payload size, ``xop:Include`` references resolve to a non-empty part, and
    declared image MIME matches magic bytes when the MIME is specific enough to verify.
    """
    report = MtomPayloadIntegrityReport(ok=True, extra={"mtom_raw_body_len": len(body)})
    ct = (response_content_type or "").lower()
    if "multipart/related" not in ct:
        soap_text = body.decode("utf-8", errors="replace")
        return soap_text, None, None, report

    outer = (response_content_type or "").strip()
    boundary = extract_boundary_from_content_type(outer)
    if not boundary:
        report.ok = False
        report.reason_code = "mtom_outer_boundary_missing"
        soap_text = body.decode("utf-8", errors="replace")
        return soap_text, None, None, report

    part_list = parse_multipart_related_parts(body, outer)
    if not part_list:
        report.ok = False
        report.reason_code = "mtom_no_parts"
        soap_text = body.decode("utf-8", errors="replace")
        return soap_text, None, None, report

    if not _multipart_has_closing_delimiter(body, boundary):
        report.ok = False
        report.reason_code = "mtom_incomplete_multipart"
        report.extra["multipart_boundary"] = boundary
        report.extra["multipart_complete"] = False
    else:
        report.extra["multipart_complete"] = True

    for hdrs, payload in part_list:
        cl_raw = hdrs.get("Content-Length") or hdrs.get("Content-length")
        if not cl_raw:
            continue
        expected = _parse_positive_int_header(str(cl_raw))
        if expected is None:
            continue
        if expected != len(payload):
            report.ok = False
            report.reason_code = "mtom_part_content_length_mismatch"
            report.extra["part_content_length_expected"] = expected
            report.extra["part_payload_len"] = len(payload)
            break

    soap_xml: str | None = None
    for hdrs, payload in part_list:
        ctype = (hdrs.get("Content-Type") or hdrs.get("Content-type") or "").lower()
        if (
            "xml" in ctype
            or payload.lstrip().startswith(b"<?xml")
            or payload.lstrip().startswith(b"<soap:")
        ):
            try:
                soap_xml = payload.decode("utf-8")
            except UnicodeDecodeError:
                soap_xml = payload.decode("utf-8", errors="replace")
            break

    if soap_xml is None:
        soap_headers, first_payload = part_list[0]
        soap_xml = first_payload.decode("utf-8", errors="replace")
        report.extra.setdefault("mtom_soap_fallback_first_part", True)

    cid_ref = extract_xop_include_cid(soap_xml)
    image_bytes: bytes | None = None
    image_ct: str | None = None
    if cid_ref:
        target = normalize_cid(f"cid:{cid_ref}")
        for hdrs, payload in part_list:
            raw_cid = hdrs.get("Content-ID") or hdrs.get("Content-Id") or ""
            if not raw_cid:
                continue
            if normalize_cid(raw_cid) != target:
                continue
            image_bytes = payload
            image_ct = hdrs.get("Content-Type") or hdrs.get("Content-type")
            break

    if cid_ref and image_bytes is None:
        report.ok = False
        report.reason_code = "mtom_missing_binary_part"
        report.extra["xop_cid"] = cid_ref
    if image_bytes is not None:
        report.extra["image_byte_len"] = len(image_bytes)
        if len(image_bytes) == 0:
            report.ok = False
            report.reason_code = "mtom_empty_binary_part"
        elif not _binary_magic_matches_declared_mime(image_ct, image_bytes):
            report.ok = False
            report.reason_code = "mtom_magic_mismatch"
            report.extra["image_content_type"] = image_ct

    return soap_xml, image_bytes, image_ct, report

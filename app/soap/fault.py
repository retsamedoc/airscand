"""SOAP 1.2 fault extraction from serialized XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.soap.xmlutil import (
    first_child_by_local,
    local_name,
    parse_soap_envelope,
    serialize_element_pretty_ns,
    soap_body,
)

_FAULT_DETAIL_LOG_MAX_LEN = 4096

_EMPTY_FAULT: dict[str, str | None] = {
    "fault_code": None,
    "fault_subcode": None,
    "fault_reason": None,
    "fault_detail": None,
}


def _extract_fault_detail(fault_el: ET.Element) -> str | None:
    """Serialize SOAP ``Detail`` children for diagnostics (truncated for logs)."""
    detail_el = first_child_by_local(fault_el, "Detail")
    if detail_el is None:
        return None
    children = list(detail_el)
    if children:
        inner = "".join(serialize_element_pretty_ns(ch) for ch in children)
    else:
        inner = "".join(detail_el.itertext()).strip()
    if not inner:
        return None
    if len(inner) > _FAULT_DETAIL_LOG_MAX_LEN:
        return inner[:_FAULT_DETAIL_LOG_MAX_LEN] + "…"
    return inner


def soap_fault_log_fields(fault: dict[str, str | None]) -> dict[str, str]:
    """Return non-empty ``fault_*`` keys suitable for ``logging`` ``extra=``."""
    out: dict[str, str] = {}
    for key in ("fault_subcode", "fault_reason", "fault_detail"):
        val = fault.get(key)
        if val:
            out[key] = val
    return out


def parse_soap_fault(text: str) -> dict[str, str | None]:
    """Extract fault code/subcode/reason/detail from SOAP fault payload."""
    fault_code: str | None = None
    fault_subcode: str | None = None
    fault_reason: str | None = None
    fault_detail: str | None = None

    env = parse_soap_envelope(text)
    if env is None:
        return dict(_EMPTY_FAULT)
    body = soap_body(env)
    if body is None:
        return dict(_EMPTY_FAULT)
    fault_el = first_child_by_local(body, "Fault")
    if fault_el is None:
        return dict(_EMPTY_FAULT)

    code_el = first_child_by_local(fault_el, "Code")
    if code_el is not None:
        for ch in code_el:
            ln = local_name(ch.tag)
            if ln == "Value" and fault_code is None:
                t = (ch.text or "").strip()
                fault_code = t if t else None
            elif ln == "Subcode":
                sv = first_child_by_local(ch, "Value")
                if sv is not None:
                    st = (sv.text or "").strip()
                    fault_subcode = st if st else None

    reason_el = first_child_by_local(fault_el, "Reason")
    if reason_el is not None:
        text_el = first_child_by_local(reason_el, "Text")
        if text_el is not None:
            rt = (text_el.text or "").strip()
            fault_reason = rt if rt else None
        if not fault_reason:
            joined = "".join(reason_el.itertext()).strip()
            fault_reason = joined if joined else None

    fault_detail = _extract_fault_detail(fault_el)

    return {
        "fault_code": fault_code,
        "fault_subcode": fault_subcode,
        "fault_reason": fault_reason,
        "fault_detail": fault_detail,
    }

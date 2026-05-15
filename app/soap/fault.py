"""SOAP 1.2 fault extraction from serialized XML."""

from __future__ import annotations

from app.soap.xmlutil import (
    first_child_by_local,
    local_name,
    parse_soap_envelope,
    soap_body,
)


def parse_soap_fault(text: str) -> dict[str, str | None]:
    """Extract fault code/subcode/reason from SOAP fault payload."""
    fault_code: str | None = None
    fault_subcode: str | None = None
    fault_reason: str | None = None

    env = parse_soap_envelope(text)
    if env is None:
        return {
            "fault_code": None,
            "fault_subcode": None,
            "fault_reason": None,
        }
    body = soap_body(env)
    if body is None:
        return {
            "fault_code": None,
            "fault_subcode": None,
            "fault_reason": None,
        }
    fault_el = first_child_by_local(body, "Fault")
    if fault_el is None:
        return {
            "fault_code": None,
            "fault_subcode": None,
            "fault_reason": None,
        }

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

    return {
        "fault_code": fault_code,
        "fault_subcode": fault_subcode,
        "fault_reason": fault_reason,
    }

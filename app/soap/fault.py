"""SOAP 1.2 fault extraction from serialized XML."""

from __future__ import annotations

import re

FAULT_CODE_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Code>.*?<soap:Value>\s*([^<\s]+)\s*</soap:Value>",
    re.DOTALL,
)
FAULT_SUBCODE_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Subcode>.*?<soap:Value>\s*([^<\s]+)\s*</soap:Value>",
    re.DOTALL,
)
FAULT_REASON_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Reason>.*?<soap:Text[^>]*>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?Text>",
    re.DOTALL,
)


def parse_soap_fault(text: str) -> dict[str, str | None]:
    """Extract fault code/subcode/reason from SOAP fault payload."""
    code_match = FAULT_CODE_PATTERN.search(text)
    subcode_match = FAULT_SUBCODE_PATTERN.search(text)
    reason_match = FAULT_REASON_PATTERN.search(text)
    return {
        "fault_code": code_match.group(1).strip() if code_match else None,
        "fault_subcode": subcode_match.group(1).strip() if subcode_match else None,
        "fault_reason": reason_match.group(1).strip() if reason_match else None,
    }

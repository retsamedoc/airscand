"""Outbound SOAP response correlation (``RelatesTo``, ``Action``) for scanner POSTs."""

from __future__ import annotations

from app.soap.addressing import extract_relates_to, extract_wsa_action
from app.soap.fault import parse_soap_fault
from app.soap.namespaces import ACTION_WSA_FAULT

__all__ = [
    "OutboundSoapCorrelationError",
    "check_outbound_soap_response_correlation",
]


class OutboundSoapCorrelationError(ValueError):
    """Raised when a scanner SOAP response does not correlate with the outbound request."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        request_message_id: str,
        relates_to: str | None,
        response_action: str | None,
        expected_success_action: str,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.request_message_id = request_message_id
        self.relates_to = relates_to
        self.response_action = response_action
        self.expected_success_action = expected_success_action


def check_outbound_soap_response_correlation(
    response_soap_text: str,
    *,
    request_message_id: str,
    expected_success_action: str,
) -> None:
    """Verify ``wsa:RelatesTo`` and ``wsa:Action`` against the outbound request.

    Some devices omit or mis-set headers (see ``docs/protocol/vendor_quirks.md``); callers
    gate this check behind configuration so default interop stays tolerant.

    SOAP faults typically use ``ACTION_WSA_FAULT`` while successful operation responses use
    the operation-specific ``…Response`` action URI.

    Args:
        response_soap_text: SOAP envelope text (full body for non-MTOM, or extracted root
            part for MTOM).
        request_message_id: ``wsa:MessageID`` sent on the matching outbound request.
        expected_success_action: Expected ``wsa:Action`` for a non-fault SOAP response.

    Raises:
        OutboundSoapCorrelationError: When headers are missing or do not match.
    """
    relates = extract_relates_to(response_soap_text)
    action = extract_wsa_action(response_soap_text)
    fault = parse_soap_fault(response_soap_text)
    has_fault = bool(fault.get("fault_code"))

    if not relates:
        raise OutboundSoapCorrelationError(
            "SOAP response missing wsa:RelatesTo (cannot correlate to outbound MessageID)",
            reason_code="missing_relates_to",
            request_message_id=request_message_id,
            relates_to=None,
            response_action=action,
            expected_success_action=expected_success_action,
        )
    if relates != request_message_id:
        raise OutboundSoapCorrelationError(
            f"SOAP response wsa:RelatesTo {relates!r} does not match request wsa:MessageID "
            f"{request_message_id!r}",
            reason_code="relates_to_mismatch",
            request_message_id=request_message_id,
            relates_to=relates,
            response_action=action,
            expected_success_action=expected_success_action,
        )

    if not action:
        raise OutboundSoapCorrelationError(
            "SOAP response missing wsa:Action",
            reason_code="missing_action",
            request_message_id=request_message_id,
            relates_to=relates,
            response_action=None,
            expected_success_action=expected_success_action,
        )

    allowed = {expected_success_action, ACTION_WSA_FAULT}
    if has_fault:
        if action not in allowed:
            raise OutboundSoapCorrelationError(
                f"SOAP fault response wsa:Action {action!r} not in expected {sorted(allowed)!r}",
                reason_code="action_mismatch_fault",
                request_message_id=request_message_id,
                relates_to=relates,
                response_action=action,
                expected_success_action=expected_success_action,
            )
    elif action != expected_success_action:
        raise OutboundSoapCorrelationError(
            f"SOAP response wsa:Action {action!r} does not match expected "
            f"{expected_success_action!r}",
            reason_code="action_mismatch",
            request_message_id=request_message_id,
            relates_to=relates,
            response_action=action,
            expected_success_action=expected_success_action,
        )

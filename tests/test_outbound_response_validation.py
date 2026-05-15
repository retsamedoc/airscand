"""Tests for outbound SOAP ``RelatesTo`` / ``Action`` correlation (WIA client §5)."""

from __future__ import annotations

import pytest

from app.soap.namespaces import (
    ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
    ACTION_WSA_FAULT,
    NS_SCA,
    NS_SOAP,
    NS_WSA,
)
from app.soap.outbound_response_validation import (
    OutboundSoapCorrelationError,
    check_outbound_soap_response_correlation,
)


def _envelope(*, relates_to: str, action: str, body_inner: str, fault: bool = False) -> str:
    """Build a minimal SOAP 1.2 envelope for correlation tests."""
    fault_xml = ""
    if fault:
        fault_xml = """
    <soap:Fault>
      <soap:Code><soap:Value>soap:Sender</soap:Value></soap:Code>
      <soap:Reason><soap:Text xml:lang="en">bad</soap:Text></soap:Reason>
    </soap:Fault>"""
    else:
        fault_xml = body_inner
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:sca="{NS_SCA}">
  <soap:Header>
    <wsa:Action>{action}</wsa:Action>
    <wsa:RelatesTo>{relates_to}</wsa:RelatesTo>
  </soap:Header>
  <soap:Body>{fault_xml}
  </soap:Body>
</soap:Envelope>"""


def test_check_correlation_accepts_matching_headers() -> None:
    """Success response with matching RelatesTo and expected Action passes."""
    mid = "urn:uuid:req-abc"
    xml = _envelope(
        relates_to=mid,
        action=ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
        body_inner="    <sca:ValidateScanTicketResponse><sca:Ticket>valid</sca:Ticket></sca:ValidateScanTicketResponse>",
    )
    check_outbound_soap_response_correlation(
        xml,
        request_message_id=mid,
        expected_success_action=ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
    )


def test_check_correlation_rejects_wrong_relates_to() -> None:
    """Mismatched RelatesTo aborts correlation (mis-matched reply to another request)."""
    xml = _envelope(
        relates_to="urn:uuid:other",
        action=ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
        body_inner="    <sca:ValidateScanTicketResponse/>",
    )
    with pytest.raises(OutboundSoapCorrelationError) as ei:
        check_outbound_soap_response_correlation(
            xml,
            request_message_id="urn:uuid:expected",
            expected_success_action=ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
        )
    assert ei.value.reason_code == "relates_to_mismatch"


def test_check_correlation_rejects_wrong_success_action() -> None:
    """Non-fault body with wrong Action fails."""
    mid = "urn:uuid:one"
    xml = _envelope(
        relates_to=mid,
        action="http://example.test/WrongAction",
        body_inner="    <sca:ValidateScanTicketResponse/>",
    )
    with pytest.raises(OutboundSoapCorrelationError) as ei:
        check_outbound_soap_response_correlation(
            xml,
            request_message_id=mid,
            expected_success_action=ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
        )
    assert ei.value.reason_code == "action_mismatch"


def test_check_correlation_allows_fault_action_with_fault_body() -> None:
    """SOAP fault with WSA fault action and matching RelatesTo is accepted."""
    mid = "urn:uuid:fault-req"
    xml = _envelope(
        relates_to=mid,
        action=ACTION_WSA_FAULT,
        body_inner="",
        fault=True,
    )
    check_outbound_soap_response_correlation(
        xml,
        request_message_id=mid,
        expected_success_action=ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
    )


def test_check_correlation_fault_body_wrong_action_fails() -> None:
    """Fault body but unexpected Action still fails."""
    mid = "urn:uuid:fault-req"
    xml = _envelope(
        relates_to=mid,
        action="http://example.test/NotFault",
        body_inner="",
        fault=True,
    )
    with pytest.raises(OutboundSoapCorrelationError) as ei:
        check_outbound_soap_response_correlation(
            xml,
            request_message_id=mid,
            expected_success_action=ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
        )
    assert ei.value.reason_code == "action_mismatch_fault"


def test_check_correlation_rejects_missing_relates_to() -> None:
    """Missing RelatesTo fails strict correlation (Canon-style omission)."""
    xml = f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}">
  <soap:Header>
    <wsa:Action>{ACTION_VALIDATE_SCAN_TICKET_RESPONSE}</wsa:Action>
  </soap:Header>
  <soap:Body/>
</soap:Envelope>"""
    with pytest.raises(OutboundSoapCorrelationError) as ei:
        check_outbound_soap_response_correlation(
            xml,
            request_message_id="urn:uuid:any",
            expected_success_action=ACTION_VALIDATE_SCAN_TICKET_RESPONSE,
        )
    assert ei.value.reason_code == "missing_relates_to"

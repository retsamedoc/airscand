"""Unit tests for inbound WS-Eventing subscribe parsing helpers."""

from __future__ import annotations

from app.soap.parsers.inbound_eventing import (
    inbound_subscribe_expires_fault_reason,
    normalize_eventing_epr_address,
    parse_inbound_subscribe_body,
)


def test_normalize_eventing_epr_address_trims_and_slash() -> None:
    """EPR normalization ignores surrounding whitespace and a trailing slash."""
    assert normalize_eventing_epr_address("  http://h/p/  ") == "http://h/p"


def test_inbound_subscribe_expires_fault_reason_accepts_absent() -> None:
    """Missing or blank ``Expires`` does not fault (server grants a default)."""
    assert inbound_subscribe_expires_fault_reason(None) is None
    assert inbound_subscribe_expires_fault_reason("   ") is None


def test_inbound_subscribe_expires_fault_reason_rejects_bad_values() -> None:
    """Non-empty unusable durations yield a fault reason string."""
    assert inbound_subscribe_expires_fault_reason("not-a-duration") is not None
    assert inbound_subscribe_expires_fault_reason("PT0S") is not None
    assert inbound_subscribe_expires_fault_reason("-PT1H") is not None


def test_inbound_subscribe_expires_fault_reason_accepts_positive() -> None:
    """Parsable positive durations are accepted."""
    assert inbound_subscribe_expires_fault_reason("PT30M") is None
    assert inbound_subscribe_expires_fault_reason("PT1H") is None


def test_parse_inbound_subscribe_body_extracts_endto() -> None:
    """Parser records ``EndTo`` presence and nested ``wsa:Address``."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing">
  <soap:Body>
    <wse:Subscribe>
      <wse:Delivery Mode="http://schemas.xmlsoap.org/ws/2004/08/eventing/DeliveryModes/Push">
        <wse:NotifyTo><wsa:Address>http://a/notify</wsa:Address></wse:NotifyTo>
      </wse:Delivery>
      <wse:EndTo><wsa:Address>http://a/notify</wsa:Address></wse:EndTo>
      <wse:Expires>PT1H</wse:Expires>
    </wse:Subscribe>
  </soap:Body>
</soap:Envelope>"""
    parsed = parse_inbound_subscribe_body(xml)
    assert parsed is not None
    assert parsed.has_end_to is True
    assert parsed.end_to_address == "http://a/notify"
    assert parsed.notify_to_address == "http://a/notify"


def test_parse_inbound_subscribe_body_endto_without_address() -> None:
    """``EndTo`` element present but empty address is visible to the handler."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing">
  <soap:Body>
    <wse:Subscribe>
      <wse:Delivery Mode="http://schemas.xmlsoap.org/ws/2004/08/eventing/DeliveryModes/Push">
        <wse:NotifyTo><wsa:Address>http://a/notify</wsa:Address></wse:NotifyTo>
      </wse:Delivery>
      <wse:EndTo></wse:EndTo>
    </wse:Subscribe>
  </soap:Body>
</soap:Envelope>"""
    parsed = parse_inbound_subscribe_body(xml)
    assert parsed is not None
    assert parsed.has_end_to is True
    assert parsed.end_to_address == ""

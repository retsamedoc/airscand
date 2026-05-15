"""Regression tests for namespace-aware WS-Eventing and WS-A SOAP parsing."""

from __future__ import annotations

from app.soap.addressing import extract_action, extract_message_id_optional
from app.soap.fault import parse_soap_fault
from app.soap.namespaces import ACTION_SUBSCRIBE, NS_SOAP, NS_WSA, NS_WSE
from app.soap.parsers.eventing import (
    effective_subscription_identifier_for_unsubscribe,
    parse_subscribe_response,
)


def test_parse_subscribe_response_accepts_alternate_prefixes() -> None:
    """Same logical document with different prefixes yields identical parsed fields."""
    xml = f"""<?xml version="1.0"?>
<e:Envelope xmlns:e="{NS_SOAP}"
  xmlns:ev="{NS_WSE}"
  xmlns:a="{NS_WSA}"
  xmlns:m="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
  <e:Body>
    <ev:SubscribeResponse>
      <m:Identifier>top-id</m:Identifier>
      <ev:SubscriptionManager>
        <a:Address>http://scanner/mgr</a:Address>
      </ev:SubscriptionManager>
      <ev:Expires>PT1H</ev:Expires>
    </ev:SubscribeResponse>
  </e:Body>
</e:Envelope>"""
    parsed = parse_subscribe_response(xml)
    assert parsed["identifier"] == "top-id"
    assert parsed["expires"] == "PT1H"
    assert parsed["subscription_manager_url"] == "http://scanner/mgr"


def test_parse_subscribe_response_body_identifier_not_epr_reference_child() -> None:
    """Direct ``SubscribeResponse`` identifier wins; nested EPR id is only in reference XML."""
    xml = f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="{NS_SOAP}"
  xmlns:wse="{NS_WSE}"
  xmlns:wsa="{NS_WSA}"
  xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
  <soap:Body>
    <wse:SubscribeResponse>
      <wsman:Identifier>body-sub</wsman:Identifier>
      <wse:SubscriptionManager>
        <wsa:Address>http://mgr</wsa:Address>
        <wsa:ReferenceParameters>
          <wse:Identifier>epr-sub</wse:Identifier>
        </wsa:ReferenceParameters>
      </wse:SubscriptionManager>
      <wse:Expires>PT1H</wse:Expires>
    </wse:SubscribeResponse>
  </soap:Body>
</soap:Envelope>"""
    parsed = parse_subscribe_response(xml)
    assert parsed["identifier"] == "body-sub"
    ref = parsed["subscription_manager_reference_parameters_xml"] or ""
    assert "epr-sub" in ref
    assert effective_subscription_identifier_for_unsubscribe("body-sub", ref) == "epr-sub"


def test_extract_action_and_message_id_alternate_wsa_prefix() -> None:
    """WS-Addressing headers resolve by namespace URI, not by ``wsa:`` prefix."""
    xml = f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:a="{NS_WSA}">
  <soap:Header>
    <a:Action>{ACTION_SUBSCRIBE}</a:Action>
    <a:MessageID>urn:uuid:alt-prefix</a:MessageID>
  </soap:Header>
  <soap:Body/>
</soap:Envelope>"""
    assert extract_action(xml) == ACTION_SUBSCRIBE
    assert extract_message_id_optional(xml) == "urn:uuid:alt-prefix"


def test_parse_soap_fault_alternate_soap_prefix() -> None:
    """Fault extraction uses SOAP 1.2 element names, not a fixed ``soap:`` prefix."""
    xml = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="{NS_SOAP}">
  <s:Body>
    <s:Fault>
      <s:Code>
        <s:Value>s:Sender</s:Value>
        <s:Subcode><s:Value>wse:FilteringNotSupported</s:Value></s:Subcode>
      </s:Code>
      <s:Reason>
        <s:Text xml:lang="en">No filter.</s:Text>
      </s:Reason>
    </s:Fault>
  </s:Body>
</s:Envelope>"""
    fault = parse_soap_fault(xml)
    assert fault["fault_code"] == "s:Sender"
    assert fault["fault_subcode"] == "wse:FilteringNotSupported"
    assert fault["fault_reason"] == "No filter."

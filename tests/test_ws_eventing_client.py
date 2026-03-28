"""Outbound WS-Eventing client tests."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from app.ws_eventing_client import (
    ACTION_CREATE_SCAN_JOB,
    ACTION_GET,
    ACTION_GET_JOB_STATUS,
    ACTION_GET_SCANNER_ELEMENTS,
    ACTION_RETRIEVE_IMAGE,
    ACTION_VALIDATE_SCAN_TICKET,
    FILTER_DIALECT_DEVPROF_ACTION,
    SCAN_AVAILABLE_EVENT_ACTION,
    build_create_scan_job_request,
    build_get_job_status_request,
    build_get_request,
    build_get_scanner_elements_request,
    build_retrieve_image_request,
    build_subscribe_request,
    build_validate_scan_ticket_request,
    extract_client_context,
    extract_event_subscription_identifier,
    extract_soap_envelope_message_id,
    get_scanner_elements_metadata,
    parse_create_scan_job_response,
    parse_get_job_status_response,
    parse_get_response,
    parse_get_scanner_elements_response,
    parse_retrieve_image_response,
    parse_soap_fault,
    parse_subscribe_response,
    parse_validate_scan_ticket_response,
    preflight_get_scanner_capabilities,
    register_with_scanner,
    resolve_scan_ticket_xml_for_chain,
    resolve_subscribe_destination_token_for_chain,
    resolve_wdp_scan_url,
    run_scan_available_chain,
)

_FAKE_GET_JOB_STATUS_COMPLETED_XML = """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:GetJobStatusResponse>
    <sca:JobState>Completed</sca:JobState>
    <sca:ImagesToTransfer>1</sca:ImagesToTransfer>
  </sca:GetJobStatusResponse></soap:Body>
</soap:Envelope>"""

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


def test_build_subscribe_request_contains_notify_to_and_to_url() -> None:
    """Subscribe request includes required headers and destination blocks."""
    mid, xml = build_subscribe_request(
        notify_to="http://192.168.1.50:5357/wsd",
        to_url="http://192.168.1.60:80/WSD/DEVICE",
        message_id="urn:uuid:req-1",
    )
    assert mid == "urn:uuid:req-1"
    assert "<wsa:Action>http://schemas.xmlsoap.org/ws/2004/08/eventing/Subscribe</wsa:Action>" in xml
    assert "<wsa:To>http://192.168.1.60:80/WSD/DEVICE</wsa:To>" in xml
    assert "<wsa:ReplyTo>" in xml
    assert "<wse:EndTo>" in xml
    assert "<wsa:ReferenceParameters>" in xml
    assert "<wse:Filter " in xml
    assert f'Dialect="{FILTER_DIALECT_DEVPROF_ACTION}"' in xml
    assert SCAN_AVAILABLE_EVENT_ACTION in xml
    assert "<sca:ScanDestinations>" in xml
    assert (
        "<wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>"
        in xml
    )
    assert "<wsa:Address>http://192.168.1.50:5357/wsd</wsa:Address>" in xml


def test_build_subscribe_request_allows_from_address() -> None:
    """Subscribe request includes optional From address when provided."""
    _, xml = build_subscribe_request(
        notify_to="http://192.168.1.50:5357/wsd",
        to_url="http://192.168.1.60:80/WSD/DEVICE",
        from_address="urn:uuid:client-1",
        message_id="urn:uuid:req-1",
    )
    assert "<wsa:From>" in xml
    assert "<wsa:Address>urn:uuid:client-1</wsa:Address>" in xml


def test_build_get_request_contains_action_and_to() -> None:
    """Get request includes WS-Transfer action and destination."""
    mid, xml = build_get_request(
        to_url="http://192.168.1.60:80/WSD/DEVICE",
        message_id="urn:uuid:get-1",
    )
    assert mid == "urn:uuid:get-1"
    assert f"<wsa:Action>{ACTION_GET}</wsa:Action>" in xml
    assert "<wsa:To>http://192.168.1.60:80/WSD/DEVICE</wsa:To>" in xml


def test_build_get_request_allows_from_address() -> None:
    """Get request includes optional From address."""
    _, xml = build_get_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        from_address="urn:uuid:client-1",
        message_id="urn:uuid:get-1",
    )
    assert "<wsa:From>" in xml
    assert "<wsa:Address>urn:uuid:client-1</wsa:Address>" in xml


def test_build_validate_scan_ticket_request_contains_expected_elements() -> None:
    """ValidateScanTicket request includes fixed ticket template and headers."""
    mid, xml = build_validate_scan_ticket_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        from_address="urn:uuid:client-1",
        message_id="urn:uuid:validate-1",
    )
    assert mid == "urn:uuid:validate-1"
    assert f"<wsa:Action>{ACTION_VALIDATE_SCAN_TICKET}</wsa:Action>" in xml
    assert "<wsa:To>http://192.168.1.60:80/WDP/SCAN</wsa:To>" in xml
    assert "<sca:ValidateScanTicketRequest>" in xml
    assert "<sca:JobName>Validating scan ticket for current WIA item properties</sca:JobName>" in xml
    assert "<sca:InputSource sca:MustHonor=\"true\">Platen</sca:InputSource>" in xml


def test_resolve_scan_ticket_xml_for_chain_prefers_device_scan_ticket() -> None:
    """DefaultScanTicket inner ScanTicket replaces the static template when present."""
    default_xml = """<sca:DefaultScanTicket xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <sca:ScanTicket>
    <sca:JobDescription>
      <sca:JobName>FromDeviceGSE</sca:JobName>
    </sca:JobDescription>
  </sca:ScanTicket>
</sca:DefaultScanTicket>"""
    out = resolve_scan_ticket_xml_for_chain(default_xml)
    assert "FromDeviceGSE" in out
    assert "Validating scan ticket for current WIA item properties" not in out


def test_resolve_scan_ticket_xml_for_chain_falls_back_without_inner_ticket() -> None:
    """Empty or missing ScanTicket keeps the Win10-like template."""
    assert "Platen" in resolve_scan_ticket_xml_for_chain("<sca:DefaultScanTicket/>")
    assert "Platen" in resolve_scan_ticket_xml_for_chain(None)


def test_resolve_scan_ticket_xml_for_chain_merges_scanner_configuration_input_source() -> None:
    """ScannerConfiguration can override InputSource when the ticket requests an unavailable source."""
    cfg = (
        "<sca:ScannerConfiguration>"
        "<sca:Platen>false</sca:Platen><sca:ADF>true</sca:ADF>"
        "</sca:ScannerConfiguration>"
    )
    out = resolve_scan_ticket_xml_for_chain(None, cfg)
    assert '<sca:InputSource sca:MustHonor="true">ADF</sca:InputSource>' in out


def test_build_validate_scan_ticket_request_uses_custom_scan_ticket_block() -> None:
    """Optional scan_ticket_xml overrides the embedded default template."""
    mid, xml = build_validate_scan_ticket_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        scan_ticket_xml=(
            "      <sca:ScanTicket><sca:JobDescription>"
            "<sca:JobName>CustomJob</sca:JobName></sca:JobDescription></sca:ScanTicket>"
        ),
    )
    assert mid
    assert "<sca:JobName>CustomJob</sca:JobName>" in xml


def test_build_create_scan_job_request_contains_expected_elements() -> None:
    """CreateScanJob request includes action and minimal body."""
    mid, xml = build_create_scan_job_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        from_address="urn:uuid:client-1",
        message_id="urn:uuid:create-1",
    )
    assert mid == "urn:uuid:create-1"
    assert f"<wsa:Action>{ACTION_CREATE_SCAN_JOB}</wsa:Action>" in xml
    assert "<wsa:To>http://192.168.1.60:80/WDP/SCAN</wsa:To>" in xml
    assert "<sca:CreateScanJobRequest>" in xml
    assert "<sca:ScanTicket>" in xml


def test_build_create_scan_job_request_includes_destination_token() -> None:
    """CreateScanJob request includes destination token when provided."""
    _, xml = build_create_scan_job_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        destination_token="token-1",
    )
    assert "<sca:DestinationToken>token-1</sca:DestinationToken>" in xml


def test_build_retrieve_image_request_contains_expected_elements() -> None:
    """RetrieveImage request includes action and required body fields."""
    mid, xml = build_retrieve_image_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        job_id="job-123",
        job_token="token-1",
        document_number="1",
        from_address="urn:uuid:client-1",
        message_id="urn:uuid:retrieve-1",
    )
    assert mid == "urn:uuid:retrieve-1"
    assert f"<wsa:Action>{ACTION_RETRIEVE_IMAGE}</wsa:Action>" in xml
    assert "<wsa:To>http://192.168.1.60:80/WDP/SCAN</wsa:To>" in xml
    assert "<sca:JobId>job-123</sca:JobId>" in xml
    assert "<sca:JobToken>token-1</sca:JobToken>" in xml
    assert "<sca:DocumentDescription>" in xml
    assert "<sca:DocumentNumber>1</sca:DocumentNumber>" in xml


def test_build_get_scanner_elements_request_contains_expected_elements() -> None:
    """GetScannerElements request includes action and requested element names."""
    mid, xml = build_get_scanner_elements_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        from_address="urn:uuid:client-1",
        message_id="urn:uuid:elements-1",
    )
    assert mid == "urn:uuid:elements-1"
    assert f"<wsa:Action>{ACTION_GET_SCANNER_ELEMENTS}</wsa:Action>" in xml
    assert "<wsa:To>http://192.168.1.60:80/WDP/SCAN</wsa:To>" in xml
    assert "<sca:GetScannerElementsRequest>" in xml
    assert "<sca:Name>sca:ScannerDescription</sca:Name>" in xml
    assert "<sca:Name>sca:DefaultScanTicket</sca:Name>" in xml
    assert "<sca:Name>sca:ScannerConfiguration</sca:Name>" in xml
    assert "<sca:Name>sca:ScannerStatus</sca:Name>" in xml


def test_build_create_scan_job_request_includes_scan_identifier() -> None:
    """CreateScanJob request includes scan identifier when provided."""
    _, xml = build_create_scan_job_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        scan_identifier="9CAED324E3C0_417441412_5",
    )
    assert "<sca:ScanIdentifier>9CAED324E3C0_417441412_5</sca:ScanIdentifier>" in xml


def test_build_create_scan_job_request_order_scan_identifier_before_destination_token() -> None:
    """CreateScanJobRequest children follow MS example: ScanIdentifier, DestinationToken, ScanTicket."""
    _, xml = build_create_scan_job_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        scan_identifier="scan-id-order",
        destination_token="dest-token-order",
    )
    pos_scan = xml.index("<sca:ScanIdentifier>scan-id-order</sca:ScanIdentifier>")
    pos_dest = xml.index("<sca:DestinationToken>dest-token-order</sca:DestinationToken>")
    pos_ticket = xml.index("<sca:ScanTicket>")
    assert pos_scan < pos_dest < pos_ticket


def test_parse_subscribe_response_identifier_and_expires() -> None:
    """Subscribe response parser extracts identifier and expiry."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing"
  xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
  <soap:Body>
    <wse:SubscribeResponse>
      <wsman:Identifier>4bda57f5-1d9e-4c3d-871b-2e9ab12c8fd4</wsman:Identifier>
      <wse:Expires>PT1H</wse:Expires>
    </wse:SubscribeResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_subscribe_response(xml)
    assert parsed["identifier"] == "4bda57f5-1d9e-4c3d-871b-2e9ab12c8fd4"
    assert parsed["expires"] == "PT1H"
    assert parsed["subscribe_destination_token"] is None


def test_parse_subscribe_response_extracts_destination_response_token() -> None:
    """SubscribeResponse DestinationResponses/DestinationToken is the spec CreateScanJob token."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/01/wdp/scan">
  <soap:Body>
    <wse:SubscribeResponse>
      <wscn:DestinationResponses>
        <wscn:DestinationResponse>
          <wscn:ClientContext>App1ScanID2345</wscn:ClientContext>
          <wscn:DestinationToken>Client3478</wscn:DestinationToken>
        </wscn:DestinationResponse>
      </wscn:DestinationResponses>
      <wse:Expires>P0Y0M0DT30H0M0S</wse:Expires>
    </wse:SubscribeResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_subscribe_response(xml)
    assert parsed["subscribe_destination_token"] == "Client3478"
    assert parsed["subscribe_destination_tokens"] == {"App1ScanID2345": "Client3478"}


def test_parse_subscribe_response_multiple_destination_responses() -> None:
    """SubscribeResponse may return one DestinationToken per ScanDestination ClientContext."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/01/wdp/scan">
  <soap:Body>
    <wse:SubscribeResponse>
      <wscn:DestinationResponses>
        <wscn:DestinationResponse>
          <wscn:ClientContext>Scan</wscn:ClientContext>
          <wscn:DestinationToken>tok-scan</wscn:DestinationToken>
        </wscn:DestinationResponse>
        <wscn:DestinationResponse>
          <wscn:ClientContext>ScanToEmail</wscn:ClientContext>
          <wscn:DestinationToken>tok-email</wscn:DestinationToken>
        </wscn:DestinationResponse>
      </wscn:DestinationResponses>
      <wse:Expires>PT1H</wse:Expires>
    </wse:SubscribeResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_subscribe_response(xml)
    assert parsed["subscribe_destination_tokens"] == {"Scan": "tok-scan", "ScanToEmail": "tok-email"}
    assert parsed["subscribe_destination_token"] == "tok-scan"


def test_extract_client_context_reads_scan_available_body() -> None:
    """ClientContext is extracted from ScanAvailableEvent-style XML."""
    xml = """<sca:ScanAvailableEvent>
      <sca:ClientContext>ScanToEmail</sca:ClientContext>
      <sca:ScanIdentifier>id-1</sca:ScanIdentifier>
    </sca:ScanAvailableEvent>"""
    assert extract_client_context(xml) == "ScanToEmail"


def test_resolve_subscribe_destination_token_prefers_matching_client_context() -> None:
    """Map lookup wins when event ClientContext matches SubscribeResponse."""
    payload = "<sca:ClientContext>ScanToEmail</sca:ClientContext>"
    assert (
        resolve_subscribe_destination_token_for_chain(
            event_payload=payload,
            subscribe_destination_tokens={"Scan": "a", "ScanToEmail": "b"},
            subscribe_destination_token="a",
            use_env_subscribe_destination_token_only=False,
        )
        == "b"
    )


def test_parse_soap_fault_extracts_code_subcode_reason() -> None:
    """Fault parser extracts code, subcode, and reason text."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Body>
    <soap:Fault>
      <soap:Code>
        <soap:Value>soap:Sender</soap:Value>
        <soap:Subcode><soap:Value>wsa:DestinationUnreachable</soap:Value></soap:Subcode>
      </soap:Code>
      <soap:Reason>
        <soap:Text xml:lang="en">No route can be determined.</soap:Text>
      </soap:Reason>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_soap_fault(xml)
    assert parsed["fault_code"] == "soap:Sender"
    assert parsed["fault_subcode"] == "wsa:DestinationUnreachable"
    assert parsed["fault_reason"] == "No route can be determined."


def test_parse_get_response_finds_wdp_scan_url_first() -> None:
    """Get response parser prefers explicit /WDP/SCAN endpoint."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body>
    <x:Info xmlns:x="urn:test">http://192.168.1.60:80/WDP/SCAN</x:Info>
    <x:Info xmlns:x="urn:test">http://192.168.1.60:80/WSDScanner</x:Info>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_get_response(xml)
    assert parsed["suggested_subscribe_to_url"] == "http://192.168.1.60:80/WDP/SCAN"


def test_parse_validate_scan_ticket_response_extracts_status() -> None:
    """Validate response parser extracts response status element."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:ValidateScanTicketResponse>
      <sca:Status>Success</sca:Status>
    </sca:ValidateScanTicketResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_validate_scan_ticket_response(xml)
    assert parsed["status"] == "Success"
    assert parsed["valid_ticket"] is None


def test_extract_event_subscription_identifier_reads_wse_identifier() -> None:
    """ScanAvailableEvent envelope may carry subscription Identifier for CreateScanJob token."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing">
  <soap:Header>
    <wse:Identifier>urn:uuid:event-sub-ref</wse:Identifier>
  </soap:Header>
  <soap:Body><sca:ScanAvailableEvent xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan"/></soap:Body>
</soap:Envelope>
"""
    assert extract_event_subscription_identifier(xml) == "urn:uuid:event-sub-ref"


def test_extract_soap_envelope_message_id_reads_header() -> None:
    """Scanner validate response MessageID is extracted for CreateScanJob DestinationToken."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Header>
    <wsa:MessageID>urn:uuid:scanner-outbound-validate</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <sca:ValidateScanTicketResponse xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
      <sca:Status>Success</sca:Status>
    </sca:ValidateScanTicketResponse>
  </soap:Body>
</soap:Envelope>
"""
    assert extract_soap_envelope_message_id(xml) == "urn:uuid:scanner-outbound-validate"


def test_parse_validate_scan_ticket_response_extracts_destination_token() -> None:
    """Validate response parser extracts destination token when present."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:ValidateScanTicketResponse>
      <sca:Status>Success</sca:Status>
      <sca:DestinationToken>dest-1</sca:DestinationToken>
    </sca:ValidateScanTicketResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_validate_scan_ticket_response(xml)
    assert parsed["destination_token"] == "dest-1"


def test_parse_validate_scan_ticket_response_extracts_valid_ticket() -> None:
    """Validate response parser extracts ValidTicket boolean text."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <wscn:ValidateScanTicketResponse>
      <wscn:ValidationInfo>
        <wscn:ValidTicket>true</wscn:ValidTicket>
      </wscn:ValidationInfo>
    </wscn:ValidateScanTicketResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_validate_scan_ticket_response(xml)
    assert parsed["valid_ticket"] == "true"


def test_parse_validate_scan_ticket_response_validation_info_without_valid_ticket_fails() -> None:
    """When ValidationInfo is present, missing ValidTicket is treated as invalid (false)."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <wscn:ValidateScanTicketResponse>
      <wscn:Status>Success</wscn:Status>
      <wscn:ValidationInfo>
        <wscn:SomeOther>1</wscn:SomeOther>
      </wscn:ValidationInfo>
    </wscn:ValidateScanTicketResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_validate_scan_ticket_response(xml)
    assert parsed["valid_ticket"] == "false"


def test_parse_validate_scan_ticket_response_self_closing_validation_info_fails() -> None:
    """Self-closing ValidationInfo has no ValidTicket."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:ValidateScanTicketResponse>
      <sca:Status>Success</sca:Status>
      <sca:ValidationInfo />
    </sca:ValidateScanTicketResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_validate_scan_ticket_response(xml)
    assert parsed["valid_ticket"] == "false"


def test_parse_create_scan_job_response_extracts_job_id() -> None:
    """CreateScanJob parser extracts JobId from response."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:CreateScanJobResponse>
      <sca:JobId>job-123</sca:JobId>
    </sca:CreateScanJobResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_create_scan_job_response(xml)
    assert parsed["job_id"] == "job-123"
    assert parsed["job_token"] is None


def test_parse_create_scan_job_response_extracts_job_token() -> None:
    """CreateScanJob parser extracts JobToken when present."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:CreateScanJobResponse>
      <sca:JobId>job-9</sca:JobId>
      <sca:JobToken>token-xyz</sca:JobToken>
    </sca:CreateScanJobResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_create_scan_job_response(xml)
    assert parsed["job_id"] == "job-9"
    assert parsed["job_token"] == "token-xyz"


def test_parse_create_scan_job_response_pairs_job_token_inside_response_only() -> None:
    """Do not use the first JobToken in the envelope if it is outside CreateScanJobResponse."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Header>
    <sca:JobToken>stale-or-echoed</sca:JobToken>
  </soap:Header>
  <soap:Body>
    <sca:CreateScanJobResponse>
      <sca:JobId>job-real</sca:JobId>
      <sca:JobToken>token-real</sca:JobToken>
    </sca:CreateScanJobResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_create_scan_job_response(xml)
    assert parsed["job_id"] == "job-real"
    assert parsed["job_token"] == "token-real"


def test_build_get_job_status_request_contains_job_identifiers() -> None:
    """GetJobStatus request includes JobId and JobToken."""
    _mid, xml = build_get_job_status_request(
        to_url="http://192.168.1.60:80/WDP/SCAN",
        job_id="jid-1",
        job_token="jtok-1",
    )
    assert ACTION_GET_JOB_STATUS.split("/")[-1] in xml
    assert "<sca:JobId>jid-1</sca:JobId>" in xml
    assert "<sca:JobToken>jtok-1</sca:JobToken>" in xml


def test_parse_get_job_status_response_extracts_state_and_images() -> None:
    """GetJobStatus parser reads JobState and ImagesToTransfer inside GetJobStatusResponse."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:GetJobStatusResponse>
      <sca:JobState>Processing</sca:JobState>
      <sca:ImagesToTransfer>0</sca:ImagesToTransfer>
    </sca:GetJobStatusResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_get_job_status_response(xml)
    assert parsed["job_state"] == "Processing"
    assert parsed["images_to_transfer"] == "0"


def test_parse_retrieve_image_response_extracts_status() -> None:
    """RetrieveImage parser extracts status field and fault details."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:RetrieveImageResponse>
      <sca:Status>Success</sca:Status>
    </sca:RetrieveImageResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_retrieve_image_response(xml)
    assert parsed["status"] == "Success"
    assert parsed["fault_subcode"] is None


def test_parse_get_scanner_elements_response_extracts_target_elements() -> None:
    """GetScannerElements parser extracts known metadata blocks."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:GetScannerElementsResponse>
      <sca:ScannerDescription><sca:Model>Epson WF-3640</sca:Model></sca:ScannerDescription>
      <sca:DefaultScanTicket><sca:DocumentParameters/></sca:DefaultScanTicket>
      <sca:ScannerConfiguration><sca:Platen>true</sca:Platen></sca:ScannerConfiguration>
      <sca:ScannerStatus><sca:State>Idle</sca:State></sca:ScannerStatus>
    </sca:GetScannerElementsResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_get_scanner_elements_response(xml)
    assert "<sca:ScannerDescription>" in (parsed["scanner_description"] or "")
    assert "<sca:DefaultScanTicket>" in (parsed["default_scan_ticket"] or "")
    assert "<sca:ScannerConfiguration>" in (parsed["scanner_configuration"] or "")
    assert "<sca:ScannerStatus>" in (parsed["scanner_status"] or "")
    assert parsed["fault_subcode"] is None


def test_resolve_wdp_scan_url_normalizes_scanner_endpoint() -> None:
    """Scanner endpoints normalize to WDP scan URL."""
    assert resolve_wdp_scan_url("http://192.168.1.60:80/WSD/DEVICE") == "http://192.168.1.60:80/WDP/SCAN"


@pytest.mark.asyncio
async def test_preflight_get_posts_and_parses_response(monkeypatch: MonkeyPatch) -> None:
    """Preflight GET posts SOAP and returns parsed endpoint hint."""
    response_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body>
    <x:Info xmlns:x="urn:test">http://192.168.1.60:80/WDP/SCAN</x:Info>
  </soap:Body>
</soap:Envelope>
"""
    captured = {}

    class DummyResponse:
        status = 200

        async def text(self) -> str:
            return response_xml

        async def __aenter__(self) -> DummyResponse:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    class DummySession:
        async def __aenter__(self) -> DummySession:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        def post(self, url: str, data: bytes, headers: dict[str, str], timeout: float) -> DummyResponse:
            captured["url"] = url
            captured["data"] = data.decode("utf-8")
            return DummyResponse()

    monkeypatch.setattr("app.ws_eventing_client.ClientSession", lambda: DummySession())
    result = await preflight_get_scanner_capabilities(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        get_to_url="http://192.168.1.60:80/WDP/SCAN",
        from_address="urn:uuid:client-1",
    )
    assert captured["url"] == "http://192.168.1.60:80/WDP/SCAN"
    assert ACTION_GET in captured["data"]
    assert "<wsa:From>" in captured["data"]
    assert result["suggested_subscribe_to_url"] == "http://192.168.1.60:80/WDP/SCAN"


@pytest.mark.asyncio
async def test_register_with_scanner_posts_and_parses_response(monkeypatch: MonkeyPatch) -> None:
    """Subscribe request posts SOAP and parses success payload."""
    response_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing"
  xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
  <soap:Body>
    <wse:SubscribeResponse>
      <wsman:Identifier>test-subscription-id</wsman:Identifier>
      <wse:Expires>PT1H</wse:Expires>
    </wse:SubscribeResponse>
  </soap:Body>
</soap:Envelope>
"""
    captured = {}

    class DummyResponse:
        status = 200

        async def text(self) -> str:
            return response_xml

        async def __aenter__(self) -> DummyResponse:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    class DummySession:
        async def __aenter__(self) -> DummySession:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        def post(self, url: str, data: bytes, headers: dict[str, str], timeout: float) -> DummyResponse:
            captured["url"] = url
            captured["data"] = data.decode("utf-8")
            captured["headers"] = headers
            captured["timeout"] = timeout
            return DummyResponse()

    monkeypatch.setattr("app.ws_eventing_client.ClientSession", lambda: DummySession())

    result = await register_with_scanner(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        subscribe_to_url="http://192.168.1.60:80/WDP/SCAN",
        notify_to="http://192.168.1.50:5357/wsd",
        from_address="urn:uuid:client-1",
        subscription_identifier="urn:uuid:sub-1",
    )
    assert captured["url"] == "http://192.168.1.60:80/WDP/SCAN"
    assert captured["headers"]["Content-Type"].startswith("application/soap+xml")
    assert "<wsa:From>" in captured["data"]
    assert "<wse:EndTo>" in captured["data"]
    assert "<wse:Identifier>urn:uuid:sub-1</wse:Identifier>" in captured["data"]
    assert "<wsa:Address>http://192.168.1.50:5357/wsd</wsa:Address>" in captured["data"]
    assert result["identifier"] == "test-subscription-id"
    assert result["expires"] == "PT1H"
    assert result["subscribe_destination_token"] is None
    assert result["status"] == "200"
    assert result["fault_subcode"] is None


@pytest.mark.asyncio
async def test_register_with_scanner_logs_non2xx_and_missing_identifier(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    """Non-2xx subscribe responses are logged with fault details."""
    caplog.set_level(logging.INFO)
    response_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Body>
    <soap:Fault>
      <soap:Code>
        <soap:Value>soap:Sender</soap:Value>
        <soap:Subcode><soap:Value>wsa:DestinationUnreachable</soap:Value></soap:Subcode>
      </soap:Code>
      <soap:Reason><soap:Text xml:lang="en">No route can be determined.</soap:Text></soap:Reason>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>
"""

    class DummyResponse:
        status = 500

        async def text(self) -> str:
            return response_xml

        async def __aenter__(self) -> DummyResponse:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    class DummySession:
        async def __aenter__(self) -> DummySession:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        def post(self, url: str, data: bytes, headers: dict[str, str], timeout: float) -> DummyResponse:
            return DummyResponse()

    monkeypatch.setattr("app.ws_eventing_client.ClientSession", lambda: DummySession())
    result = await register_with_scanner(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        notify_to="http://192.168.1.50:5357/wsd",
    )
    assert result["fault_subcode"] == "wsa:DestinationUnreachable"
    assert result["fault_code"] == "soap:Sender"
    assert "Outbound WS-Eventing subscribe returned non-success status" in caplog.text
    assert "Outbound WS-Eventing subscribe response missing Identifier" in caplog.text


@pytest.mark.asyncio
async def test_register_with_scanner_logs_timeout(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    """Timeouts are logged and propagated to callers."""
    caplog.set_level(logging.INFO)

    class DummySession:
        async def __aenter__(self) -> DummySession:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        def post(self, url: str, data: bytes, headers: dict[str, str], timeout: float) -> object:
            raise asyncio.TimeoutError()

    monkeypatch.setattr("app.ws_eventing_client.ClientSession", lambda: DummySession())
    with pytest.raises(asyncio.TimeoutError):
        await register_with_scanner(
            scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
            notify_to="http://192.168.1.50:5357/wsd",
        )
    assert "Outbound WS-Eventing subscribe timed out" in caplog.text


@pytest.mark.asyncio
async def test_get_scanner_elements_metadata_posts_and_parses_response(
    monkeypatch: MonkeyPatch,
) -> None:
    """Metadata probe posts SOAP and returns parsed scanner element blocks."""
    response_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:GetScannerElementsResponse>
      <sca:ScannerDescription><sca:Model>Epson WF-3640</sca:Model></sca:ScannerDescription>
      <sca:DefaultScanTicket><sca:DocumentParameters/></sca:DefaultScanTicket>
      <sca:ScannerConfiguration><sca:Platen>true</sca:Platen></sca:ScannerConfiguration>
      <sca:ScannerStatus><sca:State>Idle</sca:State></sca:ScannerStatus>
    </sca:GetScannerElementsResponse>
  </soap:Body>
</soap:Envelope>
"""
    captured = {}

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        captured["url"] = url
        captured["payload"] = payload
        return 200, response_xml

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await get_scanner_elements_metadata(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        get_to_url="http://192.168.1.60:80/WDP/SCAN",
    )
    assert captured["url"] == "http://192.168.1.60:80/WDP/SCAN"
    assert ACTION_GET_SCANNER_ELEMENTS in captured["payload"]
    assert "<sca:Name>sca:ScannerDescription</sca:Name>" in captured["payload"]
    assert result["status"] == "200"
    assert "<sca:ScannerDescription>" in (result["scanner_description"] or "")
    assert "<sca:DefaultScanTicket>" in (result["default_scan_ticket"] or "")
    assert "<sca:ScannerConfiguration>" in (result["scanner_configuration"] or "")
    assert "<sca:ScannerStatus>" in (result["scanner_status"] or "")


@pytest.mark.asyncio
async def test_get_scanner_elements_metadata_retries_when_invalid_args(
    monkeypatch: MonkeyPatch,
) -> None:
    """Strict devices reject unqualified Names; retry QName split matches Epson behavior."""
    fault_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <soap:Fault>
      <soap:Code>
        <soap:Value>soap:Sender</soap:Value>
        <soap:Subcode><soap:Value>wscn:InvalidArgs</soap:Value></soap:Subcode>
      </soap:Code>
      <soap:Reason><soap:Text xml:lang="en">At least one input argument is invalid</soap:Text></soap:Reason>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>
"""
    reduced_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:GetScannerElementsResponse>
      <sca:ScannerDescription><sca:Model>Epson WF-3640</sca:Model></sca:ScannerDescription>
      <sca:ScannerConfiguration><sca:Platen>true</sca:Platen></sca:ScannerConfiguration>
      <sca:ScannerStatus><sca:State>Idle</sca:State></sca:ScannerStatus>
    </sca:GetScannerElementsResponse>
  </soap:Body>
</soap:Envelope>
"""
    ticket_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:GetScannerElementsResponse>
      <sca:DefaultScanTicket><sca:DocumentParameters/></sca:DefaultScanTicket>
    </sca:GetScannerElementsResponse>
  </soap:Body>
</soap:Envelope>
"""
    gse_payloads: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            gse_payloads.append(payload)
            if len(gse_payloads) == 1:
                return 400, fault_xml
            if payload.count("<sca:Name>") == 1 and "<sca:Name>sca:DefaultScanTicket</sca:Name>" in payload:
                return 200, ticket_xml
            return 200, reduced_xml
        return 500, ""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await get_scanner_elements_metadata(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        get_to_url="http://192.168.1.60:80/WDP/SCAN",
    )
    assert len(gse_payloads) == 3
    assert "<sca:Name>sca:DefaultScanTicket</sca:Name>" in gse_payloads[0]
    assert "<sca:Name>sca:ScannerDescription</sca:Name>" in gse_payloads[1]
    assert "sca:DefaultScanTicket</sca:Name>" not in gse_payloads[1]
    assert result["status"] == "200"
    assert "<sca:DefaultScanTicket>" in (result["default_scan_ticket"] or "")


@pytest.mark.asyncio
async def test_run_scan_available_chain_success(monkeypatch: MonkeyPatch) -> None:
    """Validate then Create chain returns create result on success."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, """<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:GetScannerElementsResponse>
    <sca:DefaultScanTicket>
      <sca:ScanTicket>
        <sca:JobDescription><sca:JobName>DeviceTicketName</sca:JobName></sca:JobDescription>
      </sca:ScanTicket>
    </sca:DefaultScanTicket>
  </sca:GetScannerElementsResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status><sca:DestinationToken>dest-42</sca:DestinationToken></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-42</sca:JobId><sca:JobToken>jtok-42</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 4
    assert ACTION_GET_SCANNER_ELEMENTS in calls[0]
    assert ACTION_VALIDATE_SCAN_TICKET in calls[1]
    assert ACTION_CREATE_SCAN_JOB in calls[2]
    assert "<sca:DestinationToken>dest-42</sca:DestinationToken>" in calls[2]
    assert "<sca:JobName>DeviceTicketName</sca:JobName>" in calls[1]
    assert "<sca:JobName>DeviceTicketName</sca:JobName>" in calls[2]
    assert ACTION_RETRIEVE_IMAGE in calls[3]
    assert "<sca:JobId>job-42</sca:JobId>" in calls[3]
    assert "<sca:JobToken>jtok-42</sca:JobToken>" in calls[3]
    assert "<sca:DocumentNumber>1</sca:DocumentNumber>" in calls[3]
    assert result["validate_http_status"] == "200"
    assert result["create_http_status"] == "200"
    assert result["retrieve_http_status"] == "200"
    assert result["retrieve_status"] == "Success"
    assert result["job_id"] == "job-42"
    assert result["retrieve_elapsed_sec"] is not None
    assert float(result["retrieve_elapsed_sec"] or "0") >= 0.0


@pytest.mark.asyncio
async def test_run_scan_available_chain_polls_get_job_status_before_retrieve(
    monkeypatch: MonkeyPatch,
) -> None:
    """When polling is enabled, GetJobStatus runs after CreateScanJob and before RetrieveImage."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, """<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:GetScannerElementsResponse>
    <sca:DefaultScanTicket><sca:ScanTicket>
      <sca:JobDescription><sca:JobName>DeviceTicketName</sca:JobName></sca:JobDescription>
    </sca:ScanTicket></sca:DefaultScanTicket>
  </sca:GetScannerElementsResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status><sca:DestinationToken>dest-42</sca:DestinationToken></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-42</sca:JobId><sca:JobToken>jtok-42</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_GET_JOB_STATUS in payload:
            return 200, _FAKE_GET_JOB_STATUS_COMPLETED_XML
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    async def instant_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("app.ws_eventing_client.asyncio.sleep", instant_sleep)
    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=True,
        get_job_status_max_wait_sec=30.0,
    )
    assert len(calls) == 5
    assert ACTION_GET_JOB_STATUS in calls[3]
    assert ACTION_RETRIEVE_IMAGE in calls[4]
    assert "<sca:JobId>job-42</sca:JobId>" in calls[4]
    assert result["retrieve_http_status"] == "200"


@pytest.mark.asyncio
async def test_run_scan_available_chain_prefers_subscribe_destination_token_over_validate(
    monkeypatch: MonkeyPatch,
) -> None:
    """SubscribeResponse DestinationToken (spec) wins over validate MessageID and body."""
    calls: list[str] = []

    validate_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Header>
    <wsa:MessageID>urn:uuid:scanner-validate-response</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <sca:ValidateScanTicketResponse>
      <sca:Status>Success</sca:Status>
      <sca:DestinationToken>body-token-secondary</sca:DestinationToken>
    </sca:ValidateScanTicketResponse>
  </soap:Body>
</soap:Envelope>"""

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, validate_xml
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-sub</sca:JobId><sca:JobToken>jtok-sub</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        subscribe_destination_token="Client3478",
        poll_get_job_status_before_retrieve=False,
    )
    assert "<sca:DestinationToken>Client3478</sca:DestinationToken>" in calls[2]
    assert "scanner-validate-response" not in calls[2]
    assert "body-token-secondary" not in calls[2]
    assert result["destination_token"] == "Client3478"
    assert result["job_id"] == "job-sub"


@pytest.mark.asyncio
async def test_run_scan_available_chain_selects_token_by_event_client_context(
    monkeypatch: MonkeyPatch,
) -> None:
    """CreateScanJob uses DestinationToken for the ScanAvailableEvent ClientContext when map has multiple."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-cc</sca:JobId><sca:JobToken>jtok-cc</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    event_xml = (
        "<sca:ScanAvailableEvent>"
        "<sca:ClientContext>ScanToEmail</sca:ClientContext>"
        "<sca:ScanIdentifier>sid-1</sca:ScanIdentifier>"
        "</sca:ScanAvailableEvent>"
    )
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        scan_available_payload=event_xml,
        subscribe_destination_token="tok-scan",
        subscribe_destination_tokens={"Scan": "tok-scan", "ScanToEmail": "tok-email"},
        poll_get_job_status_before_retrieve=False,
    )
    assert "<sca:DestinationToken>tok-email</sca:DestinationToken>" in calls[2]
    assert "<sca:ScanIdentifier>sid-1</sca:ScanIdentifier>" in calls[2]
    assert result["destination_token"] == "tok-email"
    assert result["job_id"] == "job-cc"


@pytest.mark.asyncio
async def test_run_scan_available_chain_prefers_validate_response_message_id_for_destination_token(
    monkeypatch: MonkeyPatch,
) -> None:
    """Win10-style flow: when no subscribe token, DestinationToken follows validate wsa:MessageID."""
    calls: list[str] = []

    validate_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Header>
    <wsa:MessageID>urn:uuid:scanner-validate-response</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <sca:ValidateScanTicketResponse>
      <sca:Status>Success</sca:Status>
      <sca:DestinationToken>body-token-secondary</sca:DestinationToken>
    </sca:ValidateScanTicketResponse>
  </soap:Body>
</soap:Envelope>"""

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, validate_xml
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-msg</sca:JobId><sca:JobToken>jtok-msg</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert "<sca:DestinationToken>urn:uuid:scanner-validate-response</sca:DestinationToken>" in calls[2]
    assert "body-token-secondary" not in calls[2]
    assert "<sca:JobToken>jtok-msg</sca:JobToken>" in calls[3]
    assert result["job_id"] == "job-msg"


@pytest.mark.asyncio
async def test_run_scan_available_chain_stops_on_validation_failure(monkeypatch: MonkeyPatch) -> None:
    """Chain exits before CreateScanJob when validation fails."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 500, "<soap:Envelope/>"
        return 500, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body><soap:Fault><soap:Code><soap:Value>soap:Sender</soap:Value></soap:Code></soap:Fault></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 2
    assert ACTION_GET_SCANNER_ELEMENTS in calls[0]
    assert ACTION_VALIDATE_SCAN_TICKET in calls[1]
    assert result["probe_http_status"] == "500"
    assert result["create_http_status"] is None
    assert result["retrieve_http_status"] is None
    assert result["job_id"] is None


@pytest.mark.asyncio
async def test_run_scan_available_chain_stops_when_valid_ticket_false(monkeypatch: MonkeyPatch) -> None:
    """Chain exits before CreateScanJob when ValidTicket=false."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><wscn:ValidateScanTicketResponse><wscn:ValidationInfo><wscn:ValidTicket>false</wscn:ValidTicket></wscn:ValidationInfo></wscn:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 2
    assert result["valid_ticket"] == "false"
    assert result["create_http_status"] is None
    assert result["retrieve_http_status"] is None


@pytest.mark.asyncio
async def test_run_scan_available_chain_stops_when_validation_info_has_no_valid_ticket(
    monkeypatch: MonkeyPatch,
) -> None:
    """ValidationInfo without ValidTicket is invalid; chain stops before CreateScanJob."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><wscn:ValidateScanTicketResponse><wscn:Status>Success</wscn:Status>
  <wscn:ValidationInfo><wscn:Detail>pending</wscn:Detail></wscn:ValidationInfo>
  </wscn:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 2
    assert result["valid_ticket"] == "false"
    assert result["create_http_status"] is None


@pytest.mark.asyncio
async def test_run_scan_available_chain_uses_event_destination_token(monkeypatch: MonkeyPatch) -> None:
    """Event payload destination token is used when validate response omits one."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-77</sca:JobId><sca:JobToken>jtok-77</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        scan_available_payload="<sca:ScanAvailableEvent><sca:DestinationToken>event-token</sca:DestinationToken></sca:ScanAvailableEvent>",
        poll_get_job_status_before_retrieve=False,
    )
    assert "<sca:DestinationToken>event-token</sca:DestinationToken>" in calls[2]
    assert "<sca:JobToken>jtok-77</sca:JobToken>" in calls[3]
    assert result["destination_token"] == "event-token"
    assert result["retrieve_http_status"] == "200"


@pytest.mark.asyncio
async def test_run_scan_available_chain_skips_retrieve_when_create_omits_job_token(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    """RetrieveImage is not sent with DestinationToken; JobToken must come from CreateScanJobResponse."""
    caplog.set_level(logging.INFO)
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status><sca:DestinationToken>dest-2</sca:DestinationToken></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-no-token</sca:JobId></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 3
    assert ACTION_CREATE_SCAN_JOB in calls[2]
    assert result["job_id"] == "job-no-token"
    assert result["retrieve_http_status"] is None
    assert not any(ACTION_RETRIEVE_IMAGE in p for p in calls)
    assert "RetrieveImage skipped: CreateScanJobResponse omitted JobToken" in caplog.text


@pytest.mark.asyncio
async def test_run_scan_available_chain_skips_retrieve_without_job_id(monkeypatch: MonkeyPatch) -> None:
    """Chain skips RetrieveImage when CreateScanJob response omits JobId."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status><sca:DestinationToken>dest-2</sca:DestinationToken></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse/></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 3
    assert ACTION_CREATE_SCAN_JOB in calls[2]
    assert result["job_id"] is None
    assert result["retrieve_http_status"] is None


@pytest.mark.asyncio
async def test_run_scan_available_chain_prefers_event_subscription_identifier_over_config(
    monkeypatch: MonkeyPatch,
) -> None:
    """wse:Identifier on ScanAvailableEvent ranks above persisted Subscribe id for DestinationToken."""
    calls: list[str] = []

    event_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Header>
    <wse:Identifier>urn:uuid:from-notify-envelope</wse:Identifier>
  </soap:Header>
  <soap:Body>
    <wscn:ScanAvailableEvent>
      <wscn:ScanIdentifier>scan-id-1</wscn:ScanIdentifier>
    </wscn:ScanAvailableEvent>
  </soap:Body>
</soap:Envelope>"""

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><wscn:ValidateScanTicketResponse><wscn:ValidationInfo><wscn:ValidTicket>true</wscn:ValidTicket></wscn:ValidationInfo></wscn:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-ev</sca:JobId><sca:JobToken>jtok-ev</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        scan_available_payload=event_xml,
        eventing_subscription_identifier="urn:uuid:from-config-only",
        poll_get_job_status_before_retrieve=False,
    )
    assert "<sca:DestinationToken>urn:uuid:from-notify-envelope</sca:DestinationToken>" in calls[2]
    assert "from-config-only" not in calls[2]
    assert result["job_id"] == "job-ev"
    assert result["retrieve_http_status"] == "200"


@pytest.mark.asyncio
async def test_run_scan_available_chain_uses_scan_identifier_when_no_destination_token(
    monkeypatch: MonkeyPatch,
) -> None:
    """ScanIdentifier is forwarded when destination token is absent."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><wscn:ValidateScanTicketResponse><wscn:ValidationInfo><wscn:ValidTicket>true</wscn:ValidTicket></wscn:ValidationInfo></wscn:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-99</sca:JobId><sca:JobToken>jtok-99</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        scan_available_payload="<wscn:ScanAvailableEvent><wscn:ScanIdentifier>9CAED324E3C0_417441412_5</wscn:ScanIdentifier></wscn:ScanAvailableEvent>",
        eventing_subscription_identifier="4bda57f5-1d9e-4c3d-871b-2e9ab12c8fd4",
        poll_get_job_status_before_retrieve=False,
    )
    assert "<sca:ScanIdentifier>9CAED324E3C0_417441412_5</sca:ScanIdentifier>" in calls[2]
    assert (
        "<sca:DestinationToken>4bda57f5-1d9e-4c3d-871b-2e9ab12c8fd4</sca:DestinationToken>"
        in calls[2]
    )
    assert "<sca:JobToken>jtok-99</sca:JobToken>" in calls[3]
    assert result["scan_identifier"] == "9CAED324E3C0_417441412_5"


@pytest.mark.asyncio
async def test_run_scan_available_chain_retries_create_without_token_on_invalid_token_fault(
    monkeypatch: MonkeyPatch,
) -> None:
    """CreateScanJob retries once without token fields on invalid-token fault."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status><sca:DestinationToken>dest-bad</sca:DestinationToken></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload and "<sca:DestinationToken>dest-bad</sca:DestinationToken>" in payload:
            return 400, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body><soap:Fault><soap:Code><soap:Value>soap:Sender</soap:Value><soap:Subcode><soap:Value>wscn:ClientErrorInvalidDestinationToken</soap:Value></soap:Subcode></soap:Code></soap:Fault></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-retry</sca:JobId><sca:JobToken>jtok-retry</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        scan_available_payload="<wscn:ScanAvailableEvent><wscn:ScanIdentifier>sid-retry-1</wscn:ScanIdentifier></wscn:ScanAvailableEvent>",
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 5
    assert "<sca:DestinationToken>dest-bad</sca:DestinationToken>" in calls[2]
    assert "<sca:ScanIdentifier>sid-retry-1</sca:ScanIdentifier>" in calls[2]
    assert "<sca:DestinationToken>" not in calls[3]
    assert "<sca:ScanIdentifier>sid-retry-1</sca:ScanIdentifier>" in calls[3]
    assert ACTION_RETRIEVE_IMAGE in calls[4]
    assert result["create_http_status"] == "200"
    assert result["job_id"] == "job-retry"
    assert result["retrieve_http_status"] == "200"


@pytest.mark.asyncio
async def test_run_scan_available_chain_skips_retry_when_disabled(
    monkeypatch: MonkeyPatch,
) -> None:
    """When retry is disabled, invalid DestinationToken does not trigger a second CreateScanJob."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status><sca:DestinationToken>dest-bad</sca:DestinationToken></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload:
            return 400, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body><soap:Fault><soap:Code><soap:Value>soap:Sender</soap:Value><soap:Subcode><soap:Value>wscn:ClientErrorInvalidDestinationToken</soap:Value></soap:Subcode></soap:Code></soap:Fault></soap:Body>
</soap:Envelope>"""
        return 200, "<soap:Envelope/>"

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        scan_available_payload="<wscn:ScanAvailableEvent><wscn:ScanIdentifier>sid-1</wscn:ScanIdentifier></wscn:ScanAvailableEvent>",
        retry_create_without_destination_token_on_invalid_token=False,
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 3
    assert ACTION_CREATE_SCAN_JOB in calls[2]
    assert result["create_http_status"] == "400"
    assert result["retrieve_http_status"] is None


@pytest.mark.asyncio
async def test_run_scan_available_chain_create_retry_failure_still_stops(monkeypatch: MonkeyPatch) -> None:
    """CreateScanJob stops after retry failure and does not call RetrieveImage."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status><sca:DestinationToken>dest-bad</sca:DestinationToken></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload and "<sca:DestinationToken>dest-bad</sca:DestinationToken>" in payload:
            return 400, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body><soap:Fault><soap:Code><soap:Value>soap:Sender</soap:Value><soap:Subcode><soap:Value>wscn:ClientErrorInvalidDestinationToken</soap:Value></soap:Subcode></soap:Code></soap:Fault></soap:Body>
</soap:Envelope>"""
        return 400, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body><soap:Fault><soap:Code><soap:Value>soap:Sender</soap:Value><soap:Subcode><soap:Value>wscn:ClientErrorInvalidRequest</soap:Value></soap:Subcode></soap:Code></soap:Fault></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert len(calls) == 4
    assert ACTION_CREATE_SCAN_JOB in calls[2]
    assert ACTION_CREATE_SCAN_JOB in calls[3]
    assert result["create_http_status"] == "400"
    assert result["retrieve_http_status"] is None


@pytest.mark.asyncio
async def test_run_scan_available_chain_continues_when_metadata_probe_times_out(
    monkeypatch: MonkeyPatch,
) -> None:
    """Chain continues normally when metadata probe fails with timeout."""
    calls: list[str] = []

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            raise asyncio.TimeoutError()
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status><sca:DestinationToken>dest-42</sca:DestinationToken></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-42</sca:JobId><sca:JobToken>jtok-42</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""
        return 200, """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert ACTION_GET_SCANNER_ELEMENTS in calls[0]
    assert ACTION_VALIDATE_SCAN_TICKET in calls[1]
    assert result["probe_http_status"] is None
    assert result["create_http_status"] == "200"
    assert result["retrieve_http_status"] == "200"

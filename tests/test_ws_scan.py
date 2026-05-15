"""WS-Scan SOAP handler tests."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from app.inbound_eventing_registry import reset_inbound_subscription_registry
from app.soap.fault import parse_soap_fault
from app.soap.namespaces import ACTION_SUBSCRIPTION_END, ACTION_SUBSCRIPTION_END_RESPONSE
from app.soap.parsers.inbound_eventing import PUSH_DELIVERY_MODE_URI
from app.ws_scan import (
    ACTION_CREATE_SCAN_JOB,
    ACTION_GET_STATUS,
    ACTION_RENEW,
    ACTION_SCAN_AVAILABLE_EVENT,
    ACTION_SCAN_AVAILABLE_EVENT_RESPONSE,
    ACTION_SCANNER_STATUS_SUMMARY_EVENT_RESPONSE,
    ACTION_SUBSCRIBE,
    ACTION_UNSUBSCRIBE,
    SCANNER_STATUS_SUMMARY_EVENT_ACTION,
    _log_chain_result,
    build_create_scan_job_response,
    build_eventing_subscribe_response,
    build_scan_available_event_ack_response,
    build_scanner_status_summary_event_ack_response,
    build_subscription_end_ack_response,
    extract_action,
    extract_message_id,
    handle_wsd,
)

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def _reset_inbound_eventing_registry() -> None:
    """Isolate inbound subscription state across WS-Scan handler tests."""
    reset_inbound_subscription_registry()
    yield
    reset_inbound_subscription_registry()


def _scanner_status_summary_envelope(message_id: str = "urn:uuid:st-1") -> bytes:
    """SOAP notification for ScannerStatusSummaryEvent."""
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Header>
    <wsa:Action>{SCANNER_STATUS_SUMMARY_EVENT_ACTION}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <sca:ScannerStatusSummaryEvent>
      <sca:ScannerStatus><sca:State>Idle</sca:State></sca:ScannerStatus>
    </sca:ScannerStatusSummaryEvent>
  </soap:Body>
</soap:Envelope>""".encode()


def _subscribe_push_envelope(
    message_id: str = "urn:uuid:req-1",
    *,
    notify_to: str = "http://192.168.1.99:5358/client",
    manager_to: str = "http://192.168.1.50:5357/wsd",
    delivery_mode: str | None = PUSH_DELIVERY_MODE_URI,
    include_filter: bool = False,
    expires_inner: str | None = "PT1H",
    end_to_lines: str = "",
) -> bytes:
    """Valid inbound ``Subscribe`` (Push + ``NotifyTo``) for subscription manager tests."""
    filter_line = (
        '      <wse:Filter Dialect="http://schemas.xmlsoap.org/ws/2006/02/devprof/Action">x</wse:Filter>\n'
        if include_filter
        else ""
    )
    expires_lines = (
        f"      <wse:Expires>{expires_inner}</wse:Expires>\n" if expires_inner is not None else ""
    )
    mode_attr = f' Mode="{delivery_mode}"' if delivery_mode else ""
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing">
  <soap:Header>
    <wsa:Action>{ACTION_SUBSCRIBE}</wsa:Action>
    <wsa:To>{manager_to}</wsa:To>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wse:Subscribe>
      <wse:Delivery{mode_attr}>
        <wse:NotifyTo><wsa:Address>{notify_to}</wsa:Address></wse:NotifyTo>
      </wse:Delivery>
{end_to_lines}{filter_line}{expires_lines}    </wse:Subscribe>
  </soap:Body>
</soap:Envelope>""".encode()


def _subscription_end_envelope(message_id: str = "urn:uuid:end-1") -> bytes:
    """Inbound ``SubscriptionEnd`` notification toward this host's sink."""
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing"
  xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
  <soap:Header>
    <wsa:Action>{ACTION_SUBSCRIPTION_END}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wse:SubscriptionEnd>
      <wse:SubscriptionManager>
        <wsa:Address>http://scanner/mgr</wsa:Address>
        <wsman:Identifier>urn:uuid:gone</wsman:Identifier>
      </wse:SubscriptionManager>
      <wse:Status>http://schemas.xmlsoap.org/ws/2004/08/eventing/SourceShuttingDown</wse:Status>
      <wse:Reason xml:lang="en">Test</wse:Reason>
    </wse:SubscriptionEnd>
  </soap:Body>
</soap:Envelope>""".encode()


def _minimal_action_envelope(action: str, message_id: str = "urn:uuid:req-1") -> bytes:
    """Minimal SOAP envelope: only WS-A headers and empty body."""
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Header>
    <wsa:Action>{action}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body/>
</soap:Envelope>""".encode()


def _management_envelope(
    action: str,
    message_id: str,
    subscription_id: str,
    *,
    manager_to: str = "http://192.168.1.50:5357/wsd",
    renew_expires: str = "PT1H",
) -> bytes:
    """Renew / GetStatus / Unsubscribe with ``wse:Identifier`` in the SOAP header."""
    if action == ACTION_RENEW:
        body_inner = f"<wse:Renew><wse:Expires>{renew_expires}</wse:Expires></wse:Renew>"
    elif action == ACTION_GET_STATUS:
        body_inner = "<wse:GetStatus/>"
    elif action == ACTION_UNSUBSCRIBE:
        body_inner = "<wse:Unsubscribe/>"
    else:
        body_inner = ""
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing">
  <soap:Header>
    <wsa:Action>{action}</wsa:Action>
    <wsa:To>{manager_to}</wsa:To>
    <wse:Identifier>{subscription_id}</wse:Identifier>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>{body_inner}</soap:Body>
</soap:Envelope>""".encode()


def _request(payload: bytes) -> object:
    """Create a dummy aiohttp-like request for handler tests."""

    class DummyRequest:
        content_type = "application/soap+xml"

        def __init__(self, body: bytes) -> None:
            self._body = body
            self.app = {
                "config": SimpleNamespace(
                    advertise_addr="192.168.1.50",
                    port=5357,
                    endpoint_path="/wsd",
                    scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
                    uuid="11111111-2222-3333-4444-555555555555",
                    scanner_eventing_subscription_id="urn:uuid:sub-from-register",
                    scanner_subscribe_destination_token="Client3478",
                    scanner_subscribe_destination_tokens={"Scan": "Client3478"},
                    use_env_subscribe_destination_token_only=False,
                    create_scan_job_retry_invalid_destination_token=True,
                    wait_scanner_idle_after_retrieve=True,
                    scanner_idle_wait_sec=60.0,
                )
            }

        async def read(self) -> bytes:
            return self._body

    return DummyRequest(payload)


def test_extract_action_and_message_id() -> None:
    """SOAP parser extracts action and message id."""
    xml = _subscribe_push_envelope(message_id="urn:uuid:abc")
    text = xml.decode()
    assert extract_action(text) == ACTION_SUBSCRIBE
    assert extract_message_id(text) == "urn:uuid:abc"


def test_subscribe_response_includes_subscription_manager() -> None:
    """Subscribe response includes manager address and identifier."""
    xml = build_eventing_subscribe_response(
        "urn:uuid:req-1",
        "http://192.168.1.50:5357/wsd",
        "urn:uuid:sub-id-1",
        "PT1H",
    )
    assert "SubscribeResponse" in xml
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in xml
    assert "<wsa:Address>http://192.168.1.50:5357/wsd</wsa:Address>" in xml
    assert "<wsman:Identifier>urn:uuid:sub-id-1</wsman:Identifier>" in xml
    assert "<wse:Expires>PT1H</wse:Expires>" in xml


def test_create_scan_job_response_includes_job_id_and_relates_to() -> None:
    """CreateScanJob response includes job id, token, image info, and relates-to."""
    xml = build_create_scan_job_response(
        "urn:uuid:req-2",
        job_id="job-123",
        job_token="tok-456",
    )
    assert "CreateScanJobResponse" in xml
    assert "<wsa:RelatesTo>urn:uuid:req-2</wsa:RelatesTo>" in xml
    assert "<sca:JobId>job-123</sca:JobId>" in xml
    assert "<sca:JobToken>tok-456</sca:JobToken>" in xml
    assert "<sca:ImageInformation>" in xml
    assert "<sca:Width>8500</sca:Width>" in xml
    assert "<sca:Height>11700</sca:Height>" in xml
    assert "<sca:DocumentFinalParameters>" in xml
    assert "<sca:Format>exif</sca:Format>" in xml


def test_scan_available_event_ack_response_is_soap_with_relates_to() -> None:
    """ScanAvailableEvent HTTP response uses SOAP envelope and correlates via RelatesTo."""
    xml = build_scan_available_event_ack_response("urn:uuid:notify-1")
    assert "<soap:Envelope" in xml
    assert f"<wsa:Action>{ACTION_SCAN_AVAILABLE_EVENT_RESPONSE}</wsa:Action>" in xml
    assert "<wsa:RelatesTo>urn:uuid:notify-1</wsa:RelatesTo>" in xml


def test_scanner_status_summary_event_ack_response_is_soap_with_relates_to() -> None:
    """ScannerStatusSummaryEvent HTTP response uses SOAP envelope and correlates via RelatesTo."""
    xml = build_scanner_status_summary_event_ack_response("urn:uuid:status-1")
    assert "<soap:Envelope" in xml
    assert f"<wsa:Action>{ACTION_SCANNER_STATUS_SUMMARY_EVENT_RESPONSE}</wsa:Action>" in xml
    assert "<wsa:RelatesTo>urn:uuid:status-1</wsa:RelatesTo>" in xml


def test_create_scan_job_response_generates_token_when_omitted() -> None:
    """CreateScanJob response supplies JobToken when caller does not pass one."""
    xml = build_create_scan_job_response("urn:uuid:req-3", job_id="job-789")
    assert "<sca:JobId>job-789</sca:JobId>" in xml
    assert "<sca:JobToken>" in xml


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_push_returns_subscribe_response() -> None:
    """Valid inbound ``Subscribe`` returns ``SubscribeResponse`` with stable identifier."""
    response = await handle_wsd(_request(_subscribe_push_envelope()))
    text = response.text
    assert response.content_type == "application/soap+xml"
    assert "SubscribeResponse" in text
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in text
    assert "wsman:Identifier" in text


@pytest.mark.asyncio
async def test_handle_wsd_subscription_lifecycle_renew_getstatus_unsubscribe() -> None:
    """Subscribe establishes id; Renew/GetStatus read lease; Unsubscribe ends subscription."""
    sub_resp = await handle_wsd(_request(_subscribe_push_envelope("urn:uuid:M")))
    assert "SubscribeResponse" in sub_resp.text
    start = sub_resp.text.index("<wsman:Identifier>")
    end = sub_resp.text.index("</wsman:Identifier>", start)
    sub_id = sub_resp.text[start + len("<wsman:Identifier>") : end].strip()

    renew = await handle_wsd(_request(_management_envelope(ACTION_RENEW, "urn:uuid:r1", sub_id)))
    assert "RenewResponse" in renew.text
    assert "<wse:Expires>PT1H</wse:Expires>" in renew.text

    status = await handle_wsd(
        _request(_management_envelope(ACTION_GET_STATUS, "urn:uuid:g1", sub_id))
    )
    assert "GetStatusResponse" in status.text
    assert "<wse:Expires>PT1H</wse:Expires>" in status.text

    unsub = await handle_wsd(
        _request(_management_envelope(ACTION_UNSUBSCRIBE, "urn:uuid:u1", sub_id))
    )
    assert "UnsubscribeResponse" in unsub.text

    bad = await handle_wsd(_request(_management_envelope(ACTION_RENEW, "urn:uuid:r2", sub_id)))
    assert "soap:Fault" in bad.text
    fault = parse_soap_fault(bad.text)
    assert fault.get("fault_subcode") == "wse:UnableToRenew"


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_unsupported_delivery_faults() -> None:
    """Non-Push ``Delivery/@Mode`` yields ``DeliveryModeRequestedUnavailable`` fault."""
    payload = _subscribe_push_envelope(
        delivery_mode="http://schemas.xmlsoap.org/ws/2004/08/eventing/DeliveryModes/Pull"
    )
    response = await handle_wsd(_request(payload))
    assert "soap:Fault" in response.text
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:DeliveryModeRequestedUnavailable"


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_filter_faults() -> None:
    """``wse:Filter`` on inbound ``Subscribe`` yields ``FilteringNotSupported`` fault."""
    payload = _subscribe_push_envelope(include_filter=True)
    response = await handle_wsd(_request(payload))
    assert "soap:Fault" in response.text
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:FilteringNotSupported"


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_endto_empty_address_faults() -> None:
    """``wse:EndTo`` without ``wsa:Address`` yields ``InvalidMessage`` fault."""
    payload = _subscribe_push_envelope(
        end_to_lines="      <wse:EndTo></wse:EndTo>\n",
    )
    response = await handle_wsd(_request(payload))
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:InvalidMessage"


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_distinct_endto_succeeds() -> None:
    """``EndTo`` may differ from ``NotifyTo``; ``SubscriptionEnd`` is POSTed to ``EndTo`` on expiry."""
    notify = "http://192.168.1.99:5358/client"
    end_url = "http://192.168.1.77:9999/subscription-end"
    payload = _subscribe_push_envelope(
        notify_to=notify,
        end_to_lines=f"      <wse:EndTo><wsa:Address>{end_url}</wsa:Address></wse:EndTo>\n",
    )
    response = await handle_wsd(_request(payload))
    assert response.content_type == "application/soap+xml"
    assert "SubscribeResponse" in response.text


@pytest.mark.asyncio
async def test_handle_wsd_subscription_end_returns_soap_ack() -> None:
    """Inbound ``SubscriptionEnd`` yields SOAP ack with ``SubscriptionEndResponse`` action."""
    response = await handle_wsd(_request(_subscription_end_envelope()))
    assert response.content_type == "application/soap+xml"
    assert ACTION_SUBSCRIPTION_END_RESPONSE in response.text
    assert "<wsa:RelatesTo>urn:uuid:end-1</wsa:RelatesTo>" in response.text


def test_build_subscription_end_ack_matches_response_action() -> None:
    """Ack builder uses the WS-Eventing ``SubscriptionEndResponse`` action."""
    xml = build_subscription_end_ack_response("urn:uuid:mid-1")
    assert ACTION_SUBSCRIPTION_END_RESPONSE in xml


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_matching_endto_succeeds() -> None:
    """``EndTo`` matching ``NotifyTo`` (Win10-style) still returns ``SubscribeResponse``."""
    notify = "http://192.168.1.99:5358/client"
    payload = _subscribe_push_envelope(
        notify_to=notify,
        end_to_lines=(f"      <wse:EndTo><wsa:Address>{notify}</wsa:Address></wse:EndTo>\n"),
    )
    response = await handle_wsd(_request(payload))
    assert response.content_type == "application/soap+xml"
    assert "SubscribeResponse" in response.text


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_invalid_expires_faults() -> None:
    """Unparseable ``Expires`` text yields ``InvalidExpirationTime``."""
    payload = _subscribe_push_envelope(expires_inner="not-a-duration")
    response = await handle_wsd(_request(payload))
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:InvalidExpirationTime"


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_non_positive_expires_faults() -> None:
    """Zero-duration ``Expires`` yields ``InvalidExpirationTime``."""
    payload = _subscribe_push_envelope(expires_inner="PT0S")
    response = await handle_wsd(_request(payload))
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:InvalidExpirationTime"


@pytest.mark.asyncio
async def test_handle_wsd_create_scan_job_returns_response() -> None:
    """CreateScanJob returns a matching SOAP success envelope."""
    response = await handle_wsd(_request(_minimal_action_envelope(ACTION_CREATE_SCAN_JOB)))
    text = response.text
    assert response.content_type == "application/soap+xml"
    assert "CreateScanJobResponse" in text
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in text


@pytest.mark.asyncio
async def test_handle_wsd_scanner_status_summary_event_returns_soap_ack() -> None:
    """ScannerStatusSummaryEvent returns SOAP ack and correlates via RelatesTo."""
    response = await handle_wsd(_request(_scanner_status_summary_envelope()))
    assert response.status == 200
    assert response.content_type == "application/soap+xml"
    assert "<soap:Envelope" in response.text
    assert (
        f"<wsa:Action>{ACTION_SCANNER_STATUS_SUMMARY_EVENT_RESPONSE}</wsa:Action>" in response.text
    )
    assert "<wsa:RelatesTo>urn:uuid:st-1</wsa:RelatesTo>" in response.text


@pytest.mark.asyncio
async def test_handle_wsd_unknown_soap_action_returns_action_not_supported_fault() -> None:
    """Unknown SOAP actions return SOAP 1.2 fault with wsa:ActionNotSupported."""
    response = await handle_wsd(_request(_minimal_action_envelope("urn:example:UnknownAction")))
    assert response.status == 200
    assert response.content_type == "application/soap+xml"
    assert "<soap:Fault>" in response.text
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in response.text
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wsa:ActionNotSupported"
    assert fault.get("fault_reason", "").startswith("The requested WS-Addressing action")


@pytest.mark.asyncio
async def test_handle_wsd_logs_missing_action_warning(caplog: LogCaptureFixture) -> None:
    """Missing action headers are logged as warnings."""
    caplog.set_level(logging.INFO)
    payload = b"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Header/>
  <soap:Body/>
</soap:Envelope>"""
    response = await handle_wsd(_request(payload))
    assert response.content_type == "application/soap+xml"
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:InvalidMessage"
    assert "Invalid WSD SOAP request (missing Action)" in caplog.text


@pytest.mark.asyncio
async def test_handle_wsd_logs_unsupported_action_warning(caplog: LogCaptureFixture) -> None:
    """Unsupported SOAP action logs a warning before returning a fault."""
    caplog.set_level(logging.INFO)
    await handle_wsd(_request(_minimal_action_envelope("urn:example:UnknownAction")))
    assert "Unsupported WSD SOAP action; returning SOAP fault" in caplog.text


@pytest.mark.asyncio
async def test_scan_available_event_returns_ok_and_triggers_chain(
    monkeypatch: MonkeyPatch,
) -> None:
    """ScanAvailableEvent returns SOAP ack and schedules follow-up chain."""
    calls: list[tuple[str, str | None, str | None, str | None, str | None]] = []

    async def fake_chain(
        *,
        scanner_xaddr: str,
        scan_available_payload: str | None = None,
        timeout_sec: float = 5.0,
        from_address: str | None = None,
        eventing_subscription_identifier: str | None = None,
        subscribe_destination_token: str | None = None,
        subscribe_destination_tokens: dict[str, str] | None = None,
        use_env_subscribe_destination_token_only: bool = False,
        retry_create_without_destination_token_on_invalid_token: bool = True,
        **kwargs: object,
    ) -> dict[str, str | None]:
        calls.append(
            (
                scanner_xaddr,
                from_address,
                scan_available_payload,
                eventing_subscription_identifier,
                subscribe_destination_token,
            )
        )
        assert subscribe_destination_tokens == {"Scan": "Client3478"}
        assert use_env_subscribe_destination_token_only is False
        return {
            "target_url": "http://192.168.1.60:80/WDP/SCAN",
            "validate_http_status": "200",
            "create_http_status": "200",
            "job_id": "job-1",
        }

    monkeypatch.setattr("app.ws_scan.run_scan_available_chain", fake_chain)
    response = await handle_wsd(_request(_minimal_action_envelope(ACTION_SCAN_AVAILABLE_EVENT)))
    await asyncio.sleep(0)
    assert response.status == 200
    assert response.content_type == "application/soap+xml"
    assert "<soap:Envelope" in response.text
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in response.text
    assert calls[0][0] == "http://192.168.1.60:80/WSD/DEVICE"
    assert calls[0][1] == "urn:uuid:11111111-2222-3333-4444-555555555555"
    assert ACTION_SCAN_AVAILABLE_EVENT in (calls[0][2] or "")
    assert calls[0][3] == "urn:uuid:sub-from-register"
    assert calls[0][4] == "Client3478"


@pytest.mark.asyncio
async def test_scan_available_event_chain_failure_does_not_change_response(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    """Chain failures are logged while response remains generic success."""
    caplog.set_level(logging.INFO)

    async def failing_chain(
        *,
        scanner_xaddr: str,
        scan_available_payload: str | None = None,
        timeout_sec: float = 5.0,
        from_address: str | None = None,
        eventing_subscription_identifier: str | None = None,
        subscribe_destination_token: str | None = None,
        subscribe_destination_tokens: dict[str, str] | None = None,
        use_env_subscribe_destination_token_only: bool = False,
        retry_create_without_destination_token_on_invalid_token: bool = True,
        **kwargs: object,
    ) -> dict[str, str | None]:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.ws_scan.run_scan_available_chain", failing_chain)
    response = await handle_wsd(_request(_minimal_action_envelope(ACTION_SCAN_AVAILABLE_EVENT)))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert response.status == 200
    assert response.content_type == "application/soap+xml"
    assert "<soap:Envelope" in response.text
    assert any("ScanAvailable follow-up chain failed" in message for message in caplog.messages)


@pytest.mark.asyncio
async def test_log_chain_result_ignores_cancelled_task(caplog: LogCaptureFixture) -> None:
    """Cancelled ScanAvailable follow-up task is logged without raising."""
    caplog.set_level(logging.INFO)

    async def _never() -> dict[str, str | None]:
        await asyncio.sleep(10)
        return {}

    task = asyncio.create_task(_never())
    task.cancel()
    await asyncio.sleep(0)
    _log_chain_result(task)

    assert any(
        "ScanAvailable follow-up chain cancelled during shutdown" in message
        for message in caplog.messages
    )

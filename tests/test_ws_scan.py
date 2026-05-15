"""WS-Scan SOAP handler tests."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from app.inbound_eventing_registry import inbound_eventing_registry
from app.soap.fault import parse_soap_fault
from app.soap.namespaces import (
    SCAN_AVAILABLE_EVENT_ACTION,
    WSE_DELIVERY_MODE_PUSH,
)
from app.soap.parsers.eventing import EXPIRES_PATTERN, parse_subscribe_response
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
    extract_action,
    extract_message_id,
    handle_wsd,
)

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def _reset_inbound_eventing_registry() -> None:
    """Isolate inbound subscription state across tests."""
    inbound_eventing_registry().reset_for_testing()
    yield


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


def _soap_envelope(action: str, message_id: str = "urn:uuid:req-1") -> bytes:
    """Build a compact SOAP envelope for action tests (body shape ignored except Subscribe)."""
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing">
  <soap:Header>
    <wsa:Action>{action}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wse:Subscribe />
  </soap:Body>
</soap:Envelope>""".encode()


def _valid_subscribe_envelope(
    *,
    message_id: str = "urn:uuid:req-1",
    notify_to: str = "http://192.168.1.50:5357/wsd",
    include_filter: bool = True,
    delivery_mode: str = WSE_DELIVERY_MODE_PUSH,
    filter_action: str = SCAN_AVAILABLE_EVENT_ACTION,
    filter_dialect: str = "http://schemas.xmlsoap.org/ws/2006/02/devprof/Action",
) -> bytes:
    """Minimal valid inbound ``Subscribe`` for the local event source (Push + optional Action filter)."""
    filt = ""
    if include_filter:
        filt = f'      <wse:Filter Dialect="{filter_dialect}">{filter_action}</wse:Filter>\n'
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing">
  <soap:Header>
    <wsa:Action>{ACTION_SUBSCRIBE}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wse:Subscribe>
      <wse:Delivery Mode="{delivery_mode}">
        <wse:NotifyTo>
          <wsa:Address>{notify_to}</wsa:Address>
        </wse:NotifyTo>
      </wse:Delivery>
{filt}      <wse:Expires>PT1H</wse:Expires>
    </wse:Subscribe>
  </soap:Body>
</soap:Envelope>""".encode()


def _management_envelope(
    action: str,
    subscription_id: str,
    *,
    message_id: str = "urn:uuid:mgmt-1",
    renew_expires: str | None = "PT1H",
) -> bytes:
    """WS-Eventing management request with ``wse:Identifier`` in the SOAP header."""
    if action == ACTION_RENEW:
        body = (
            f"<wse:Renew><wse:Expires>{renew_expires}</wse:Expires></wse:Renew>"
            if renew_expires
            else "<wse:Renew/>"
        )
    elif action == ACTION_GET_STATUS:
        body = "<wse:GetStatus/>"
    elif action == ACTION_UNSUBSCRIBE:
        body = "<wse:Unsubscribe/>"
    else:
        body = "<wse:Renew/>"
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing">
  <soap:Header>
    <wsa:To>http://192.168.1.50:5357/wsd</wsa:To>
    <wse:Identifier>{subscription_id}</wse:Identifier>
    <wsa:Action>{action}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    {body}
  </soap:Body>
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
    xml = _soap_envelope(ACTION_SUBSCRIBE, message_id="urn:uuid:abc")
    text = xml.decode()
    assert extract_action(text) == ACTION_SUBSCRIBE
    assert extract_message_id(text) == "urn:uuid:abc"


def test_subscribe_response_includes_subscription_manager() -> None:
    """Subscribe response includes manager address and identifier."""
    xml = build_eventing_subscribe_response(
        "urn:uuid:req-1",
        "http://192.168.1.50:5357/wsd",
        identifier="sub-fixed-1",
        expires="PT30M",
    )
    assert "SubscribeResponse" in xml
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in xml
    assert "<wsa:Address>http://192.168.1.50:5357/wsd</wsa:Address>" in xml
    assert "wsman:Identifier" in xml
    assert "sub-fixed-1" in xml
    assert "<wse:Expires>PT30M</wse:Expires>" in xml


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
async def test_handle_wsd_subscribe_without_filter_succeeds() -> None:
    """Subscribe may omit ``wse:Filter`` when the peer does not request filtering."""
    response = await handle_wsd(_request(_valid_subscribe_envelope(include_filter=False)))
    assert response.status == 200
    assert "SubscribeResponse" in response.text


@pytest.mark.asyncio
async def test_handle_wsd_subscribe_valid_returns_subscribe_response() -> None:
    """Inbound Subscribe with Push + filter returns SubscribeResponse and registers id."""
    response = await handle_wsd(_request(_valid_subscribe_envelope()))
    assert response.status == 200
    assert response.content_type == "application/soap+xml"
    assert "SubscribeResponse" in response.text
    parsed = parse_subscribe_response(response.text)
    assert parsed.get("identifier")
    assert parsed.get("expires")


@pytest.mark.asyncio
async def test_handle_wsd_create_scan_job_returns_response() -> None:
    """CreateScanJob SOAP action returns matching SOAP response."""
    response = await handle_wsd(_request(_soap_envelope(ACTION_CREATE_SCAN_JOB)))
    text = response.text
    assert response.content_type == "application/soap+xml"
    assert "CreateScanJobResponse" in text
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [ACTION_RENEW, ACTION_GET_STATUS, ACTION_UNSUBSCRIBE],
)
async def test_handle_wsd_eventing_management_requires_prior_subscribe(action: str) -> None:
    """Renew / GetStatus / Unsubscribe without a live subscription return SOAP fault."""
    response = await handle_wsd(_request(_management_envelope(action, "not-a-real-id")))
    assert response.status == 500
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:UnableToRenew"


@pytest.mark.asyncio
async def test_inbound_eventing_subscribe_renew_getstatus_unsubscribe_lifecycle() -> None:
    """Identifier from Subscribe is honored through Renew, GetStatus, then Unsubscribe faults."""
    sub_resp = await handle_wsd(_request(_valid_subscribe_envelope(message_id="urn:uuid:m-1")))
    assert sub_resp.status == 200
    sub_id = parse_subscribe_response(sub_resp.text)["identifier"]
    assert sub_id

    renew_resp = await handle_wsd(
        _request(_management_envelope(ACTION_RENEW, sub_id, message_id="urn:uuid:r-1"))
    )
    assert renew_resp.status == 200
    assert "RenewResponse" in renew_resp.text

    gs1 = await handle_wsd(
        _request(_management_envelope(ACTION_GET_STATUS, sub_id, message_id="urn:uuid:g-1"))
    )
    assert gs1.status == 200
    assert "GetStatusResponse" in gs1.text

    unsub = await handle_wsd(
        _request(_management_envelope(ACTION_UNSUBSCRIBE, sub_id, message_id="urn:uuid:u-1"))
    )
    assert unsub.status == 200
    assert "UnsubscribeResponse" in unsub.text

    bad = await handle_wsd(
        _request(_management_envelope(ACTION_RENEW, sub_id, message_id="urn:uuid:r-2"))
    )
    assert bad.status == 500
    assert parse_soap_fault(bad.text).get("fault_subcode") == "wse:UnableToRenew"


@pytest.mark.asyncio
async def test_inbound_subscribe_fault_unsupported_delivery_mode() -> None:
    """Non-Push delivery mode yields DeliveryModeRequestedUnavailable fault."""
    bad = _valid_subscribe_envelope(
        delivery_mode="http://schemas.xmlsoap.org/ws/2004/08/eventing/DeliveryModes/Pull"
    )
    response = await handle_wsd(_request(bad))
    assert response.status == 500
    assert (
        parse_soap_fault(response.text).get("fault_subcode")
        == "wse:DeliveryModeRequestedUnavailable"
    )


@pytest.mark.asyncio
async def test_inbound_subscribe_fault_unsupported_filter() -> None:
    """Unsupported filter dialect yields FilteringNotSupported fault."""
    bad = _valid_subscribe_envelope(
        include_filter=True,
        filter_dialect="http://example.com/unsupported",
        filter_action=SCAN_AVAILABLE_EVENT_ACTION,
    )
    response = await handle_wsd(_request(bad))
    assert response.status == 500
    assert parse_soap_fault(response.text).get("fault_subcode") == "wse:FilteringNotSupported"


@pytest.mark.asyncio
async def test_get_status_stable_when_clock_frozen(monkeypatch: MonkeyPatch) -> None:
    """Two GetStatus calls at the same instant return identical Expires (no hidden renew)."""
    t0 = 1_700_000_000.0
    monkeypatch.setattr("app.inbound_eventing_registry.time.time", lambda: t0)
    sub_resp = await handle_wsd(_request(_valid_subscribe_envelope(message_id="urn:uuid:freeze-1")))
    sub_id = parse_subscribe_response(sub_resp.text)["identifier"]
    assert sub_id
    a = await handle_wsd(
        _request(_management_envelope(ACTION_GET_STATUS, sub_id, message_id="urn:uuid:gs-a"))
    )
    b = await handle_wsd(
        _request(_management_envelope(ACTION_GET_STATUS, sub_id, message_id="urn:uuid:gs-b"))
    )
    assert a.status == 200 and b.status == 200
    ex_a = EXPIRES_PATTERN.search(a.text)
    ex_b = EXPIRES_PATTERN.search(b.text)
    assert ex_a is not None and ex_b is not None
    assert ex_a.group(1).strip() == ex_b.group(1).strip()


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
async def test_handle_wsd_non_eventing_action_falls_back_to_plain_ok() -> None:
    """Unknown SOAP actions use plain-text fallback response."""
    response = await handle_wsd(_request(_soap_envelope("urn:example:UnknownAction")))
    assert response.content_type == "text/plain"
    assert response.text == "OK"


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
    assert response.content_type == "text/plain"
    assert "Invalid WSD SOAP request (missing Action)" in caplog.text


@pytest.mark.asyncio
async def test_handle_wsd_logs_unsupported_action_warning(caplog: LogCaptureFixture) -> None:
    """Unsupported action fallback logs warning message."""
    caplog.set_level(logging.INFO)
    await handle_wsd(_request(_soap_envelope("urn:example:UnknownAction")))
    assert "Unsupported WSD SOAP action; using plain OK fallback" in caplog.text


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
    response = await handle_wsd(_request(_soap_envelope(ACTION_SCAN_AVAILABLE_EVENT)))
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
    response = await handle_wsd(_request(_soap_envelope(ACTION_SCAN_AVAILABLE_EVENT)))
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

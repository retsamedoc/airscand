"""WS-Scan SOAP handler tests."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from app.ws_scan import (
    ACTION_CREATE_SCAN_JOB,
    ACTION_GET_STATUS,
    ACTION_RENEW,
    ACTION_SCAN_AVAILABLE_EVENT,
    ACTION_SCAN_AVAILABLE_EVENT_RESPONSE,
    ACTION_SUBSCRIBE,
    ACTION_UNSUBSCRIBE,
    _log_chain_result,
    build_create_scan_job_response,
    build_eventing_subscribe_response,
    build_scan_available_event_ack_response,
    extract_action,
    extract_message_id,
    handle_wsd,
)

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


def _soap_envelope(action: str, message_id: str = "urn:uuid:req-1") -> bytes:
    """Build a compact SOAP envelope for action tests."""
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
    xml = build_eventing_subscribe_response("urn:uuid:req-1", "http://192.168.1.50:5357/wsd")
    assert "SubscribeResponse" in xml
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in xml
    assert "<wsa:Address>http://192.168.1.50:5357/wsd</wsa:Address>" in xml
    assert "wsman:Identifier" in xml
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


def test_create_scan_job_response_generates_token_when_omitted() -> None:
    """CreateScanJob response supplies JobToken when caller does not pass one."""
    xml = build_create_scan_job_response("urn:uuid:req-3", job_id="job-789")
    assert "<sca:JobId>job-789</sca:JobId>" in xml
    assert "<sca:JobToken>" in xml


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (ACTION_SUBSCRIBE, "SubscribeResponse"),
        (ACTION_RENEW, "RenewResponse"),
        (ACTION_GET_STATUS, "GetStatusResponse"),
        (ACTION_UNSUBSCRIBE, "UnsubscribeResponse"),
        (ACTION_CREATE_SCAN_JOB, "CreateScanJobResponse"),
    ],
)
async def test_handle_wsd_eventing_actions(action: str, expected: str) -> None:
    """Each supported SOAP action returns a matching SOAP response."""
    response = await handle_wsd(_request(_soap_envelope(action)))
    text = response.text
    assert response.content_type == "application/soap+xml"
    assert expected in text
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in text


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
    calls: list[
        tuple[str, str | None, str | None, str | None, str | None]
    ] = []

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

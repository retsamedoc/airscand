"""Outbound WS-Eventing client tests."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from app.ws_eventing_client import (
    ACTION_GET,
    FILTER_DIALECT_DEVPROF_ACTION,
    SCAN_AVAILABLE_EVENT_ACTION,
    build_get_request,
    build_subscribe_request,
    parse_get_response,
    parse_soap_fault,
    parse_subscribe_response,
    preflight_get_scanner_capabilities,
    register_with_scanner,
)

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

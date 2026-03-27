from types import SimpleNamespace
import logging

import pytest

from app.ws_scan import (
    ACTION_GET_STATUS,
    ACTION_RENEW,
    ACTION_SUBSCRIBE,
    ACTION_UNSUBSCRIBE,
    build_eventing_subscribe_response,
    extract_action,
    extract_message_id,
    handle_wsd,
)


def _soap_envelope(action: str, message_id: str = "urn:uuid:req-1") -> bytes:
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


def _request(payload: bytes):
    class DummyRequest:
        content_type = "application/soap+xml"

        def __init__(self, body):
            self._body = body
            self.app = {
                "config": SimpleNamespace(
                    advertise_addr="192.168.1.50",
                    port=5357,
                    endpoint_path="/wsd",
                )
            }

        async def read(self):
            return self._body

    return DummyRequest(payload)


def test_extract_action_and_message_id():
    xml = _soap_envelope(ACTION_SUBSCRIBE, message_id="urn:uuid:abc")
    text = xml.decode()
    assert extract_action(text) == ACTION_SUBSCRIBE
    assert extract_message_id(text) == "urn:uuid:abc"


def test_subscribe_response_includes_subscription_manager():
    xml = build_eventing_subscribe_response("urn:uuid:req-1", "http://192.168.1.50:5357/wsd")
    assert "SubscribeResponse" in xml
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in xml
    assert "<wsa:Address>http://192.168.1.50:5357/wsd</wsa:Address>" in xml
    assert "wsman:Identifier" in xml
    assert "<wse:Expires>PT1H</wse:Expires>" in xml


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (ACTION_SUBSCRIBE, "SubscribeResponse"),
        (ACTION_RENEW, "RenewResponse"),
        (ACTION_GET_STATUS, "GetStatusResponse"),
        (ACTION_UNSUBSCRIBE, "UnsubscribeResponse"),
    ],
)
async def test_handle_wsd_eventing_actions(action: str, expected: str):
    response = await handle_wsd(_request(_soap_envelope(action)))
    text = response.text
    assert response.content_type == "application/soap+xml"
    assert expected in text
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in text


@pytest.mark.asyncio
async def test_handle_wsd_non_eventing_action_falls_back_to_plain_ok():
    response = await handle_wsd(_request(_soap_envelope("urn:example:UnknownAction")))
    assert response.content_type == "text/plain"
    assert response.text == "OK"


@pytest.mark.asyncio
async def test_handle_wsd_logs_missing_action_warning(caplog):
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
async def test_handle_wsd_logs_unsupported_action_warning(caplog):
    caplog.set_level(logging.INFO)
    await handle_wsd(_request(_soap_envelope("urn:example:UnknownAction")))
    assert "Unsupported WSD SOAP action; using plain OK fallback" in caplog.text

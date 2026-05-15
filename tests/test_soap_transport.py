"""Tests for :mod:`app.soap.transport` timeout wiring."""

from __future__ import annotations

import asyncio
from errno import ECONNREFUSED

import pytest
from aiohttp import ClientTimeout
from aiohttp.client_exceptions import ClientConnectorError, ClientOSError

from app.config import Config
from app.soap.transport import (
    SoapHttpClient,
    configure_soap_http_client_from_config,
    default_soap_http_client,
    http_body_integrity_from_aiohttp_response,
    is_scanner_xaddr_transport_failover,
    reset_soap_http_client_singleton_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_default_soap_singleton() -> None:
    """Avoid leaking configured singleton across tests."""
    reset_soap_http_client_singleton_for_tests()
    yield
    reset_soap_http_client_singleton_for_tests()


class _FakeResponse:
    """Minimal aiohttp-like response for ``post`` context manager."""

    status = 200
    headers: dict[str, str] = {}
    content_length: int | None = None

    def __init__(self, body_text: str = "", *, content_length: int | None = None) -> None:
        self._body_text = body_text
        self.content_length = content_length

    async def text(self) -> str:
        return self._body_text

    async def read(self) -> bytes:
        return self._body_text.encode("utf-8")

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeSession:
    """Captures ``timeout=`` passed to ``post``."""

    closed = False

    def __init__(self, body_xml: str) -> None:
        self.body_xml = body_xml
        self.last_timeout: ClientTimeout | None = None

    def post(self, *args: object, **kwargs: object) -> _FakeResponse:
        self.last_timeout = kwargs.get("timeout")
        return _FakeResponse(self.body_xml)


def _minimal_response_xml() -> str:
    """SOAP envelope with ``wsa:Action`` so transport logging path stays realistic."""
    return """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Header>
    <wsa:Action>http://example.test/OkResponse</wsa:Action>
  </soap:Header>
  <soap:Body/>
</soap:Envelope>"""


@pytest.mark.asyncio
async def test_soap_http_client_post_text_uses_distinct_connect_and_read_timeouts() -> None:
    """``ClientTimeout`` uses ``sock_connect`` from the client and ``sock_read`` from the call."""
    session = _FakeSession(_minimal_response_xml())
    client = SoapHttpClient(
        session=session,
        connect_timeout_sec=2.25,
        read_timeout_override_sec=None,
    )
    await client.post_text(url="http://127.0.0.1:9/soap", payload="<x/>", timeout_sec=40.0)
    assert session.last_timeout is not None
    assert session.last_timeout.sock_connect == 2.25
    assert session.last_timeout.sock_read == 40.0


@pytest.mark.asyncio
async def test_soap_http_client_read_timeout_override_replaces_per_call_read() -> None:
    """When ``read_timeout_override_sec`` is set, it becomes ``sock_read`` regardless of call."""
    session = _FakeSession(_minimal_response_xml())
    client = SoapHttpClient(
        session=session,
        connect_timeout_sec=1.0,
        read_timeout_override_sec=99.5,
    )
    await client.post_text(url="http://127.0.0.1:9/soap", payload="<x/>", timeout_sec=5.0)
    assert session.last_timeout is not None
    assert session.last_timeout.sock_connect == 1.0
    assert session.last_timeout.sock_read == 99.5


@pytest.mark.asyncio
async def test_soap_http_client_post_retrieve_image_uses_same_timeout_split() -> None:
    """``post_retrieve_image`` applies the same connect vs read policy as ``post_text``."""
    session = _FakeSession(_minimal_response_xml())
    client = SoapHttpClient(
        session=session, connect_timeout_sec=3.0, read_timeout_override_sec=None
    )
    status, _body, _ct, rep = await client.post_retrieve_image(
        url="http://127.0.0.1:9/retrieve",
        payload="<x/>",
        timeout_sec=120.0,
    )
    assert status == 200
    assert rep.ok is True
    assert session.last_timeout is not None
    assert session.last_timeout.sock_connect == 3.0
    assert session.last_timeout.sock_read == 120.0


def test_http_body_integrity_from_aiohttp_response_mismatch() -> None:
    """When ``content_length`` disagrees with actual bytes, the report is not OK."""

    class _Resp:
        content_length = 100
        headers: dict[str, str] = {}

    rep = http_body_integrity_from_aiohttp_response(b"x" * 5, _Resp())
    assert rep.ok is False
    assert rep.reason_code == "http_content_length_mismatch"
    assert rep.body_len == 5
    assert rep.content_length == 100


def test_http_body_integrity_from_aiohttp_response_no_header() -> None:
    """Chunked or omitted ``Content-Length`` yields OK (length not asserted)."""

    class _Resp:
        content_length = None
        headers: dict[str, str] = {}

    rep = http_body_integrity_from_aiohttp_response(b"abc", _Resp())
    assert rep.ok is True
    assert rep.content_length is None


def test_configure_soap_http_client_from_config_applies_config_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``configure_soap_http_client_from_config`` matches :class:`~app.config.Config` SOAP fields."""
    monkeypatch.setenv("WSD_SOAP_HTTP_CONNECT_TIMEOUT_SEC", "7.25")
    monkeypatch.delenv("WSD_SOAP_HTTP_READ_TIMEOUT_SEC", raising=False)

    cfg = Config()
    configure_soap_http_client_from_config(cfg)
    client = default_soap_http_client()
    assert client._connect_timeout_sec == 7.25
    assert client._read_timeout_override_sec is None


def test_is_scanner_xaddr_transport_failover_timeout() -> None:
    """Timeouts map to trying the next discovered **XAddr**."""
    assert is_scanner_xaddr_transport_failover(asyncio.TimeoutError()) is True


def test_is_scanner_xaddr_transport_failover_connector_and_os() -> None:
    """Connection refused and connector errors map to **XAddr** failover."""
    assert is_scanner_xaddr_transport_failover(
        ClientConnectorError(connection_key=None, os_error=OSError(ECONNREFUSED, "refused"))
    )
    assert is_scanner_xaddr_transport_failover(ClientOSError(ECONNREFUSED, "refused"))


def test_is_scanner_xaddr_transport_failover_excludes_app_errors() -> None:
    """Non-transport exceptions do not trigger **XAddr** rotation."""
    assert is_scanner_xaddr_transport_failover(ValueError("bad")) is False

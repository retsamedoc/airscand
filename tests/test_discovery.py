"""WS-Discovery helper and handler tests."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from app.discovery import (
    ACTION_BYE,
    ACTION_HELLO,
    ACTION_PROBE,
    ACTION_PROBE_MATCHES,
    ACTION_RESOLVE,
    NS_WSCN,
    NS_WSD,
    SELF_PROBE_TTL_SEC,
    _recent_outbound_probe_ids,
    _recv_discovery_match,
    _remember_outbound_probe_id,
    build_bye,
    build_hello,
    build_probe,
    build_probe_match,
    build_resolve,
    build_resolve_matches,
    discover_scanner_xaddr,
    extract_action,
    extract_relates_to,
    extract_resolve_epr_address,
    extract_xaddrs,
    handle_discovery_packet,
)

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


class DummySocket:
    """Capture UDP payloads sent by discovery handlers."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, payload: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((payload, addr))


def make_config(**kwargs: Any) -> SimpleNamespace:
    """Build a minimal config namespace for discovery tests."""
    base = dict(
        uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        advertise_addr="192.168.1.50",
        port=5357,
        endpoint_path="/wsd",
        metadata_version=1,
        app_sequence_instance_id=4,
        app_sequence_sequence_id="urn:uuid:c22d45fe-bdf5-4925-b4e1-30da581fd709",
        hello_interval_sec=60.0,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _probe_envelope(message_id: str = "uuid:abc-123") -> bytes:
    """Build a Probe SOAP envelope for packet tests."""
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <soap:Header>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>{ACTION_PROBE}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wsd:Probe><wsd:Types>wsdp:Device</wsd:Types></wsd:Probe>
  </soap:Body>
</soap:Envelope>
""".encode()


def test_build_probe_match_discovery_namespace_and_types() -> None:
    """ProbeMatches payload includes expected namespaces and types."""
    cfg = make_config()
    xml = build_probe_match(cfg, "uuid:probe-123", "http://192.168.1.50:5357/wsd")
    assert f'xmlns:wsd="{NS_WSD}"' in xml
    assert f'xmlns:wscn="{NS_WSCN}"' in xml
    assert "<wsa:RelatesTo>uuid:probe-123</wsa:RelatesTo>" in xml
    assert "wsdp:Device pub:Computer wscn:ScanDeviceType" in xml
    assert "<wsd:XAddrs>http://192.168.1.50:5357/wsd</wsd:XAddrs>" in xml
    assert "ProbeMatches" in xml


def test_build_resolve_matches_relates_to() -> None:
    """ResolveMatches payload carries relates-to and expected types."""
    cfg = make_config()
    xml = build_resolve_matches(cfg, "urn:uuid:resolve-mid-1", "http://192.168.1.50:5357/wsd")
    assert "ResolveMatches" in xml
    assert "<wsa:RelatesTo>urn:uuid:resolve-mid-1</wsa:RelatesTo>" in xml
    assert "wsdp:Device pub:Computer wscn:ScanDeviceType" in xml


def test_build_hello_has_computer_types_and_app_sequence() -> None:
    """Hello payload contains AppSequence and device type metadata."""
    cfg = make_config()
    xml = build_hello(cfg, message_number=1)
    assert "discovery/Hello" in xml
    assert "wsdp:Device pub:Computer" in xml
    assert 'InstanceId="4"' in xml
    assert "urn:uuid:c22d45fe-bdf5-4925-b4e1-30da581fd709" in xml
    assert 'MessageNumber="1"' in xml


def test_build_bye_has_epr_app_sequence_and_bye_action() -> None:
    """Bye payload mirrors Hello EPR and AppSequence with Bye action."""
    cfg = make_config()
    xml = build_bye(cfg, message_number=2)
    assert ACTION_BYE in xml
    assert "wsd:Bye" in xml
    assert "urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in xml
    assert 'MessageNumber="2"' in xml
    assert 'InstanceId="4"' in xml


def test_extract_action_and_resolve_epr() -> None:
    """Action and resolve EPR parsing returns expected values."""
    sample = _probe_envelope().decode()
    assert extract_action(sample) == ACTION_PROBE

    resolve_xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <soap:Body>
    <wsd:Resolve>
      <wsa:EndpointReference>
        <wsa:Address>urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</wsa:Address>
      </wsa:EndpointReference>
    </wsd:Resolve>
  </soap:Body>
</soap:Envelope>"""
    assert extract_resolve_epr_address(resolve_xml) == (
        "urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )


def test_extract_relates_to_and_xaddrs() -> None:
    """RelatesTo and XAddrs parser extracts all expected values."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <soap:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>
    <wsa:RelatesTo>urn:uuid:probe-1</wsa:RelatesTo>
  </soap:Header>
  <soap:Body>
    <wsd:ProbeMatches>
      <wsd:ProbeMatch>
        <wsd:XAddrs>http://192.168.1.60:80/WSD/DEVICE http://192.168.1.61/WSD/DEVICE</wsd:XAddrs>
      </wsd:ProbeMatch>
    </wsd:ProbeMatches>
  </soap:Body>
</soap:Envelope>"""
    assert extract_relates_to(xml) == "urn:uuid:probe-1"
    assert extract_xaddrs(xml) == [
        "http://192.168.1.60:80/WSD/DEVICE",
        "http://192.168.1.61/WSD/DEVICE",
    ]


def test_build_probe_and_resolve() -> None:
    """Probe and Resolve payload builders include expected fields."""
    probe_mid, probe_xml = build_probe("urn:uuid:probe-mid")
    resolve_mid, resolve_xml = build_resolve(
        "urn:uuid:cfe92100-67c4-11d4-a45f-9caed324e3c0",
        "urn:uuid:resolve-mid",
    )
    assert probe_mid == "urn:uuid:probe-mid"
    assert f"<wsa:Action>{ACTION_PROBE}</wsa:Action>" in probe_xml
    assert "wscn:ScanDeviceType" in probe_xml
    assert resolve_mid == "urn:uuid:resolve-mid"
    assert f"<wsa:Action>{ACTION_RESOLVE}</wsa:Action>" in resolve_xml
    assert "urn:uuid:cfe92100-67c4-11d4-a45f-9caed324e3c0" in resolve_xml


def test_handle_discovery_packet_replies_with_probematches() -> None:
    """Probe packets produce ProbeMatches responses."""
    cfg = make_config()
    sock = DummySocket()
    handled = handle_discovery_packet(cfg, _probe_envelope(), ("10.0.0.44", 3702), sock)

    assert handled is True
    assert len(sock.sent) == 1
    payload, addr = sock.sent[0]
    text = payload.decode()
    assert addr == ("10.0.0.44", 3702)
    assert "ProbeMatches" in text
    assert "<wsa:RelatesTo>uuid:abc-123</wsa:RelatesTo>" in text
    assert "<wsd:XAddrs>http://192.168.1.50:5357/wsd</wsd:XAddrs>" in text


def test_handle_discovery_packet_ignores_recent_self_probe_and_logs(
    caplog: LogCaptureFixture,
) -> None:
    """Self-origin probes are ignored and logged at debug level."""
    cfg = make_config()
    sock = DummySocket()
    caplog.set_level(logging.DEBUG)
    _recent_outbound_probe_ids.clear()
    _remember_outbound_probe_id("uuid:abc-123")
    try:
        handled = handle_discovery_packet(cfg, _probe_envelope(), ("10.0.0.44", 3702), sock)
    finally:
        _recent_outbound_probe_ids.clear()

    assert handled is False
    assert sock.sent == []
    matches = [r for r in caplog.records if r.message == "Probe ignored by self-filter policy"]
    assert matches
    assert matches[-1].levelno == logging.DEBUG


def test_handle_discovery_packet_does_not_ignore_expired_self_probe(
    monkeypatch: MonkeyPatch,
) -> None:
    """Expired self-probe cache entries no longer suppress handling."""
    cfg = make_config()
    sock = DummySocket()
    _recent_outbound_probe_ids.clear()
    _remember_outbound_probe_id("uuid:abc-123", now=10.0)
    monkeypatch.setattr("app.discovery.time.monotonic", lambda: 10.0 + SELF_PROBE_TTL_SEC + 1.0)
    try:
        handled = handle_discovery_packet(cfg, _probe_envelope(), ("10.0.0.44", 3702), sock)
    finally:
        _recent_outbound_probe_ids.clear()

    assert handled is True
    assert len(sock.sent) == 1


def test_handle_discovery_ignores_probematches_action() -> None:
    """Inbound ProbeMatches action is ignored by server handler."""
    cfg = make_config()
    sock = DummySocket()
    probematches = b"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>
    <wsa:MessageID>urn:uuid:x</wsa:MessageID>
  </soap:Header>
  <soap:Body/>
</soap:Envelope>"""
    assert handle_discovery_packet(cfg, probematches, ("10.0.0.44", 3702), sock) is False
    assert sock.sent == []


def test_handle_discovery_resolve_matches_when_epr_matches() -> None:
    """Resolve with matching EPR produces ResolveMatches response."""
    cfg = make_config()
    sock = DummySocket()
    body = f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <soap:Header>
    <wsa:Action>{ACTION_RESOLVE}</wsa:Action>
    <wsa:MessageID>urn:uuid:res-1</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wsd:Resolve>
      <wsa:EndpointReference>
        <wsa:Address>urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</wsa:Address>
      </wsa:EndpointReference>
    </wsd:Resolve>
  </soap:Body>
</soap:Envelope>""".encode()

    handled = handle_discovery_packet(cfg, body, ("10.0.0.11", 3702), sock)
    assert handled is True
    assert len(sock.sent) == 1
    text = sock.sent[0][0].decode()
    assert "ResolveMatches" in text
    assert "<wsa:RelatesTo>urn:uuid:res-1</wsa:RelatesTo>" in text


def test_handle_discovery_resolve_ignored_on_epr_mismatch() -> None:
    """Resolve with non-matching EPR is ignored."""
    cfg = make_config()
    sock = DummySocket()
    body = f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <soap:Header>
    <wsa:Action>{ACTION_RESOLVE}</wsa:Action>
    <wsa:MessageID>urn:uuid:res-1</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wsd:Resolve>
      <wsa:EndpointReference>
        <wsa:Address>urn:uuid:00000000-0000-0000-0000-000000000000</wsa:Address>
      </wsa:EndpointReference>
    </wsd:Resolve>
  </soap:Body>
</soap:Envelope>""".encode()

    assert handle_discovery_packet(cfg, body, ("10.0.0.11", 3702), sock) is False
    assert sock.sent == []


def test_discover_scanner_xaddr_uses_config_override() -> None:
    """Configured scanner_xaddr bypasses active discovery."""
    cfg = make_config(scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE")
    assert asyncio.run(discover_scanner_xaddr(cfg)) == "http://192.168.1.60:80/WSD/DEVICE"


def test_discover_scanner_xaddr_from_probe_matches(monkeypatch: MonkeyPatch) -> None:
    """Active discovery returns XAddr from ProbeMatches payload."""
    cfg = make_config(scanner_xaddr="")

    class DummySock:
        def sendto(self, _data: bytes, _addr: tuple[str, int]) -> None:
            return None

        def setsockopt(self, *_args: object) -> None:
            return None

        def setblocking(self, _v: bool) -> None:
            return None

        def close(self) -> None:
            return None

    async def fake_recv(sock: object, timeout_sec: float) -> tuple[str, str, list[str]]:
        return (
            ACTION_PROBE_MATCHES,
            "urn:uuid:probe-1",
            ["http://192.168.1.60:80/WSD/DEVICE"],
        )

    monkeypatch.setattr("app.discovery._build_ws_discovery_client_socket", lambda: DummySock())
    monkeypatch.setattr("app.discovery._recv_discovery_match", fake_recv)
    monkeypatch.setattr("app.discovery.build_probe", lambda: ("urn:uuid:probe-1", "<x/>"))
    monkeypatch.setattr("app.discovery.time.monotonic", lambda: SELF_PROBE_TTL_SEC + 10.0)

    xaddr = asyncio.run(discover_scanner_xaddr(cfg, timeout_sec=0.1, max_attempts=1))
    assert xaddr == "http://192.168.1.60:80/WSD/DEVICE"


def test_handle_discovery_packet_logs_invalid_missing_action(caplog: LogCaptureFixture) -> None:
    """Missing action packets are rejected and logged."""
    cfg = make_config()
    sock = DummySocket()
    caplog.set_level(logging.INFO)
    assert handle_discovery_packet(cfg, b"<soap:Envelope/>", ("10.0.0.44", 3702), sock) is False
    assert "Invalid discovery packet (missing Action)" in caplog.text


def test_handle_discovery_packet_logs_unsupported_action(caplog: LogCaptureFixture) -> None:
    """Unsupported actions are logged with warning severity."""
    cfg = make_config()
    sock = DummySocket()
    caplog.set_level(logging.INFO)
    payload = b"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Header>
    <wsa:Action>urn:example:Unknown</wsa:Action>
    <wsa:MessageID>urn:uuid:x</wsa:MessageID>
  </soap:Header>
</soap:Envelope>"""
    assert handle_discovery_packet(cfg, payload, ("10.0.0.44", 3702), sock) is False
    assert "Unsupported discovery action" in caplog.text


def test_handle_discovery_packet_hello_does_not_warn(caplog: LogCaptureFixture) -> None:
    """Hello packets do not trigger unsupported-action warnings."""
    cfg = make_config()
    sock = DummySocket()
    caplog.set_level(logging.DEBUG)
    payload = f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Header>
    <wsa:Action>{ACTION_HELLO}</wsa:Action>
    <wsa:MessageID>urn:uuid:hello-1</wsa:MessageID>
  </soap:Header>
</soap:Envelope>""".encode()
    assert handle_discovery_packet(cfg, payload, ("10.0.0.44", 3702), sock) is False
    assert "Unsupported discovery action" not in caplog.text
    assert any(
        r.message == "Unsolicited discovery message observed" and r.levelno == logging.DEBUG
        for r in caplog.records
    )


def test_handle_discovery_packet_bye_does_not_warn(caplog: LogCaptureFixture) -> None:
    """Bye packets do not trigger unsupported-action warnings."""
    cfg = make_config()
    sock = DummySocket()
    caplog.set_level(logging.DEBUG)
    payload = f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
  <soap:Header>
    <wsa:Action>{ACTION_BYE}</wsa:Action>
    <wsa:MessageID>urn:uuid:bye-1</wsa:MessageID>
  </soap:Header>
</soap:Envelope>""".encode()
    assert handle_discovery_packet(cfg, payload, ("10.0.0.44", 3702), sock) is False
    assert "Unsupported discovery action" not in caplog.text
    assert any(
        r.message == "Unsolicited discovery message observed" and r.levelno == logging.DEBUG
        for r in caplog.records
    )


def test_discovery_packet_received_is_debug_for_cached_message_id(
    caplog: LogCaptureFixture,
) -> None:
    """Cached self-probe ids downgrade ingress logging to debug."""
    cfg = make_config()
    sock = DummySocket()
    caplog.set_level(logging.DEBUG)
    _recent_outbound_probe_ids.clear()
    _remember_outbound_probe_id("uuid:abc-123")
    try:
        handle_discovery_packet(cfg, _probe_envelope(), ("10.0.0.44", 3702), sock)
    finally:
        _recent_outbound_probe_ids.clear()
    received = [r for r in caplog.records if r.message == "Discovery packet received"]
    assert received
    assert received[-1].levelno == logging.DEBUG


def test_recv_discovery_match_logs_invalid_packet(
    caplog: LogCaptureFixture,
    monkeypatch: MonkeyPatch,
) -> None:
    """Invalid match packet logs warning and returns None."""
    caplog.set_level(logging.INFO)

    async def fake_wait_for(_awaitable: object, timeout: float) -> tuple[bytes, tuple[str, int]]:
        try:
            await _awaitable
        except Exception:
            pass
        return (b"<soap:Envelope/>", ("10.0.0.6", 3702))

    monkeypatch.setattr("app.discovery.asyncio.wait_for", fake_wait_for)

    class DummySock:
        pass

    assert asyncio.run(_recv_discovery_match(DummySock(), timeout_sec=0.01)) is None
    assert "Invalid discovery match packet" in caplog.text

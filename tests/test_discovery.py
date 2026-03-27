import asyncio
import logging
from types import SimpleNamespace

from app.discovery import (
    ACTION_BYE,
    ACTION_HELLO,
    ACTION_PROBE,
    ACTION_PROBE_MATCHES,
    ACTION_RESOLVE,
    SELF_PROBE_TTL_SEC,
    _remember_outbound_probe_id,
    _recent_outbound_probe_ids,
    build_probe,
    build_resolve,
    NS_WSD,
    NS_WSCN,
    discover_scanner_xaddr,
    build_hello,
    build_probe_match,
    build_resolve_matches,
    extract_action,
    extract_relates_to,
    extract_resolve_epr_address,
    extract_xaddrs,
    _recv_discovery_match,
    handle_discovery_packet,
)


class DummySocket:
    def __init__(self) -> None:
        self.sent = []

    def sendto(self, payload: bytes, addr) -> None:
        self.sent.append((payload, addr))


def make_config(**kwargs):
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


def test_build_probe_match_discovery_namespace_and_types():
    cfg = make_config()
    xml = build_probe_match(cfg, "uuid:probe-123", "http://192.168.1.50:5357/wsd")
    assert f'xmlns:wsd="{NS_WSD}"' in xml
    assert f'xmlns:wscn="{NS_WSCN}"' in xml
    assert "<wsa:RelatesTo>uuid:probe-123</wsa:RelatesTo>" in xml
    assert "wsdp:Device pub:Computer wscn:ScanDeviceType" in xml
    assert "<wsd:XAddrs>http://192.168.1.50:5357/wsd</wsd:XAddrs>" in xml
    assert "ProbeMatches" in xml


def test_build_resolve_matches_relates_to():
    cfg = make_config()
    xml = build_resolve_matches(cfg, "urn:uuid:resolve-mid-1", "http://192.168.1.50:5357/wsd")
    assert "ResolveMatches" in xml
    assert "<wsa:RelatesTo>urn:uuid:resolve-mid-1</wsa:RelatesTo>" in xml
    assert "wsdp:Device pub:Computer wscn:ScanDeviceType" in xml


def test_build_hello_has_computer_types_and_app_sequence():
    cfg = make_config()
    xml = build_hello(cfg, message_number=1)
    assert "discovery/Hello" in xml
    assert "wsdp:Device pub:Computer" in xml
    assert 'InstanceId="4"' in xml
    assert "urn:uuid:c22d45fe-bdf5-4925-b4e1-30da581fd709" in xml
    assert 'MessageNumber="1"' in xml


def test_extract_action_and_resolve_epr():
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


def test_extract_relates_to_and_xaddrs():
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


def test_build_probe_and_resolve():
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


def test_handle_discovery_packet_replies_with_probematches():
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


def test_handle_discovery_packet_ignores_recent_self_probe_and_logs(caplog):
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


def test_handle_discovery_packet_does_not_ignore_expired_self_probe(monkeypatch):
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


def test_handle_discovery_ignores_probematches_action():
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


def test_handle_discovery_resolve_matches_when_epr_matches():
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


def test_handle_discovery_resolve_ignored_on_epr_mismatch():
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


def test_discover_scanner_xaddr_uses_config_override():
    cfg = make_config(scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE")
    assert (
        asyncio.run(discover_scanner_xaddr(cfg))
        == "http://192.168.1.60:80/WSD/DEVICE"
    )


def test_discover_scanner_xaddr_from_probe_matches(monkeypatch):
    cfg = make_config(scanner_xaddr="")

    class DummySock:
        def sendto(self, _data, _addr):
            return None

        def setsockopt(self, *_args):
            return None

        def setblocking(self, _v):
            return None

        def close(self):
            return None

    async def fake_recv(sock, timeout_sec):
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


def test_handle_discovery_packet_logs_invalid_missing_action(caplog):
    cfg = make_config()
    sock = DummySocket()
    caplog.set_level(logging.INFO)
    assert handle_discovery_packet(cfg, b"<soap:Envelope/>", ("10.0.0.44", 3702), sock) is False
    assert "Invalid discovery packet (missing Action)" in caplog.text


def test_handle_discovery_packet_logs_unsupported_action(caplog):
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


def test_handle_discovery_packet_hello_does_not_warn(caplog):
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


def test_handle_discovery_packet_bye_does_not_warn(caplog):
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


def test_discovery_packet_received_is_debug_for_cached_message_id(caplog):
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


def test_recv_discovery_match_logs_invalid_packet(caplog, monkeypatch):
    caplog.set_level(logging.INFO)

    async def fake_wait_for(_awaitable, timeout):
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

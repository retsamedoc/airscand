from types import SimpleNamespace

from app.discovery import build_probe_match, handle_discovery_packet


class DummySocket:
    def __init__(self) -> None:
        self.sent = []

    def sendto(self, payload: bytes, addr) -> None:
        self.sent.append((payload, addr))


def make_config():
    return SimpleNamespace(
        uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        advertise_addr="192.168.1.50",
        port=5357,
        endpoint_path="/wsd",
    )


def test_build_probe_match_includes_namespaces_and_relates_to():
    cfg = make_config()
    xml = build_probe_match(cfg, "uuid:probe-123", "http://192.168.1.50:5357/wsd")
    assert 'xmlns:wsd="http://schemas.microsoft.com/windows/2006/08/wdp/scan"' in xml
    assert "<wsa:RelatesTo>uuid:probe-123</wsa:RelatesTo>" in xml
    assert "<d:Types>wsd:ScanDeviceType</d:Types>" in xml
    assert "<d:XAddrs>http://192.168.1.50:5357/wsd</d:XAddrs>" in xml


def test_handle_discovery_packet_replies_with_probematches():
    cfg = make_config()
    sock = DummySocket()
    probe = b"""<?xml version="1.0"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <e:Header>
    <wsa:MessageID>uuid:abc-123</wsa:MessageID>
  </e:Header>
  <e:Body>
    <d:Probe />
  </e:Body>
</e:Envelope>
"""

    handled = handle_discovery_packet(cfg, probe, ("10.0.0.44", 3702), sock)

    assert handled is True
    assert len(sock.sent) == 1
    payload, addr = sock.sent[0]
    text = payload.decode()
    assert addr == ("10.0.0.44", 3702)
    assert "ProbeMatches" in text
    assert "<wsa:RelatesTo>uuid:abc-123</wsa:RelatesTo>" in text
    assert "<d:XAddrs>http://192.168.1.50:5357/wsd</d:XAddrs>" in text

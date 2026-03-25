import asyncio
import socket
import logging
import re
import uuid

MULTICAST_GROUP = "239.255.255.250"
PORT = 3702

log = logging.getLogger(__name__)

MESSAGE_ID_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?MessageID>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?MessageID>"
)


def extract_message_id(text: str) -> str:
    match = MESSAGE_ID_PATTERN.search(text)
    if not match:
        return "uuid:unknown"
    return match.group(1).strip()


def build_probe_match(config, relates_to, xaddr):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:wsd="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <e:Header>
    <wsa:MessageID>uuid:{uuid.uuid4()}</wsa:MessageID>
    <wsa:RelatesTo>{relates_to}</wsa:RelatesTo>
    <wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>
  </e:Header>
  <e:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <wsa:EndpointReference>
          <wsa:Address>urn:uuid:{config.uuid}</wsa:Address>
        </wsa:EndpointReference>
        <d:Types>wsd:ScanDeviceType</d:Types>
        <d:XAddrs>{xaddr}</d:XAddrs>
        <d:MetadataVersion>1</d:MetadataVersion>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </e:Body>
</e:Envelope>
"""


def build_xaddr(config) -> str:
    return f"http://{config.advertise_addr}:{config.port}{config.endpoint_path}"


def handle_discovery_packet(config, data: bytes, addr, sock) -> bool:
    text = data.decode(errors="ignore")
    if "Probe" not in text:
        return False

    relates_to = extract_message_id(text)
    xaddr = build_xaddr(config)
    response = build_probe_match(config, relates_to, xaddr)
    sock.sendto(response.encode(), addr)
    log.info(
        "ProbeMatch sent",
        extra={"addr": str(addr), "relates_to": relates_to, "xaddr": xaddr},
    )
    return True


async def start_discovery(config):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", PORT))

    mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton("0.0.0.0")
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setblocking(False)

    log.info("WSD discovery listening")

    loop = asyncio.get_running_loop()

    while True:
        data, addr = await loop.sock_recvfrom(sock, 8192)
        handled = handle_discovery_packet(config, data, addr, sock)
        if handled:
            log.info("Probe received", extra={"addr": str(addr)})

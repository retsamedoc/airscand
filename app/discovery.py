import asyncio
import socket
import logging
import uuid

MULTICAST_GROUP = "239.255.255.250"
PORT = 3702

log = logging.getLogger(__name__)

def build_probe_match(config, relates_to):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
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
        <d:XAddrs>http://{socket.gethostbyname(socket.gethostname())}:{config.port}{config.endpoint_path}</d:XAddrs>
        <d:MetadataVersion>1</d:MetadataVersion>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </e:Body>
</e:Envelope>
"""

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
        text = data.decode(errors="ignore")

        if "Probe" in text:
            log.info("Probe received", extra={"addr": addr})

            # naive extraction (refine later)
            relates_to = "uuid:unknown"

            response = build_probe_match(config, relates_to)
            sock.sendto(response.encode(), addr)

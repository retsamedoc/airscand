"""WS-Discovery protocol helpers and multicast service loop."""

import asyncio
import logging
import re
import socket
import time
import uuid

from app.config import Config

MULTICAST_GROUP = "239.255.255.250"
PORT = 3702

NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
NS_WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
NS_WSA_ROLE_ANONYMOUS = "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous"
NS_WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
NS_WSDP = "http://schemas.xmlsoap.org/ws/2006/02/devprof"
NS_PUB = "http://schemas.microsoft.com/windows/pub/2005/07"
NS_WSCN = "http://schemas.microsoft.com/windows/2006/08/wdp/scan"

ACTION_PROBE = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe"
ACTION_RESOLVE = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Resolve"
ACTION_PROBE_MATCHES = "http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches"
ACTION_RESOLVE_MATCHES = "http://schemas.xmlsoap.org/ws/2005/04/discovery/ResolveMatches"
ACTION_HELLO = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Hello"
ACTION_BYE = "http://schemas.xmlsoap.org/ws/2005/04/discovery/Bye"

# Self-probe filter tuning knobs. Keep these near the top for easy policy changes.
SELF_PROBE_TTL_SEC = 300.0
SELF_PROBE_CACHE_MAX = 256

log = logging.getLogger(__name__)

_recent_outbound_probe_ids: dict[str, float] = {}

MESSAGE_ID_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?MessageID>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?MessageID>"
)
ACTION_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Action>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Action>"
)
RELATES_TO_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?RelatesTo>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?RelatesTo>"
)
XADDR_PATTERN = re.compile(r"<(?:[A-Za-z0-9_]+:)?XAddrs>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?XAddrs>")


def extract_message_id(text: str) -> str:
    match = MESSAGE_ID_PATTERN.search(text)
    if not match:
        return "uuid:unknown"
    return match.group(1).strip()


def extract_action(text: str) -> str | None:
    match = ACTION_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip()


def extract_relates_to(text: str) -> str | None:
    match = RELATES_TO_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip()


def extract_xaddrs(text: str) -> list[str]:
    match = XADDR_PATTERN.search(text)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split() if part.strip()]


def extract_resolve_epr_address(text: str) -> str | None:
    lower = text.lower()
    key = "resolve"
    idx = lower.find(f"<wsd:{key}>")
    if idx == -1:
        idx = lower.find(f"<d:{key}>")
    if idx == -1:
        idx = lower.find("<resolve>")
    if idx == -1:
        return None
    window = text[idx:]
    match = re.search(
        r"<(?:[A-Za-z0-9_]+:)?Address>\s*([^<\s]+)\s*</(?:[A-Za-z0-9_]+:)?Address>",
        window,
    )
    return match.group(1).strip() if match else None


def our_epr(config: Config) -> str:
    """Build this service endpoint reference address."""
    return f"urn:uuid:{config.uuid}"


def build_xaddr(config: Config) -> str:
    """Build externally advertised service URL."""
    return f"http://{config.advertise_addr}:{config.port}{config.endpoint_path}"


def _new_message_id() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def build_probe(message_id: str | None = None) -> tuple[str, str]:
    mid = message_id or _new_message_id()
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:wsd="{NS_WSD}" xmlns:wscn="{NS_WSCN}">
  <soap:Header>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>{ACTION_PROBE}</wsa:Action>
    <wsa:MessageID>{mid}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wsd:Probe>
      <wsd:Types>wscn:ScanDeviceType</wsd:Types>
    </wsd:Probe>
  </soap:Body>
</soap:Envelope>
"""
    return mid, body


def build_resolve(endpoint_reference: str, message_id: str | None = None) -> tuple[str, str]:
    mid = message_id or _new_message_id()
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:wsd="{NS_WSD}">
  <soap:Header>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>{ACTION_RESOLVE}</wsa:Action>
    <wsa:MessageID>{mid}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
    <wsd:Resolve>
      <wsa:EndpointReference>
        <wsa:Address>{endpoint_reference}</wsa:Address>
      </wsa:EndpointReference>
    </wsd:Resolve>
  </soap:Body>
</soap:Envelope>
"""
    return mid, body


def build_hello(config: Config, message_number: int) -> str:
    """Build a WS-Discovery Hello announcement payload."""
    xaddr = build_xaddr(config)
    msg_id = _new_message_id()
    sequence_id = getattr(config, "app_sequence_sequence_id", "") or our_epr(config)
    instance_id = getattr(config, "app_sequence_instance_id", 1)
    meta = getattr(config, "metadata_version", 1)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:wsd="{NS_WSD}" xmlns:wsdp="{NS_WSDP}" xmlns:pub="{NS_PUB}">
  <soap:Header>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Hello</wsa:Action>
    <wsa:MessageID>{msg_id}</wsa:MessageID>
    <wsd:AppSequence InstanceId="{instance_id}" SequenceId="{sequence_id}" MessageNumber="{message_number}"/>
  </soap:Header>
  <soap:Body>
    <wsd:Hello>
      <wsa:EndpointReference>
        <wsa:Address>{our_epr(config)}</wsa:Address>
      </wsa:EndpointReference>
      <wsd:Types>wsdp:Device pub:Computer</wsd:Types>
      <wsd:XAddrs>{xaddr}</wsd:XAddrs>
      <wsd:MetadataVersion>{meta}</wsd:MetadataVersion>
    </wsd:Hello>
  </soap:Body>
</soap:Envelope>
"""


def build_bye(config: Config, message_number: int) -> str:
    """Build a WS-Discovery Bye message (departure announcement)."""
    msg_id = _new_message_id()
    sequence_id = getattr(config, "app_sequence_sequence_id", "") or our_epr(config)
    instance_id = getattr(config, "app_sequence_instance_id", 1)
    meta = getattr(config, "metadata_version", 1)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:wsd="{NS_WSD}" xmlns:wsdp="{NS_WSDP}" xmlns:pub="{NS_PUB}">
  <soap:Header>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>{ACTION_BYE}</wsa:Action>
    <wsa:MessageID>{msg_id}</wsa:MessageID>
    <wsd:AppSequence InstanceId="{instance_id}" SequenceId="{sequence_id}" MessageNumber="{message_number}"/>
  </soap:Header>
  <soap:Body>
    <wsd:Bye>
      <wsa:EndpointReference>
        <wsa:Address>{our_epr(config)}</wsa:Address>
      </wsa:EndpointReference>
      <wsd:MetadataVersion>{meta}</wsd:MetadataVersion>
    </wsd:Bye>
  </soap:Body>
</soap:Envelope>
"""


def _probe_match_types() -> str:
    return "wsdp:Device pub:Computer wscn:ScanDeviceType"


def build_probe_match(
    config: Config,
    relates_to: str,
    xaddr: str,
    outbound_message_id: str | None = None,
) -> str:
    """Build ProbeMatches response payload."""
    mid = outbound_message_id or _new_message_id()
    meta = getattr(config, "metadata_version", 1)
    types = _probe_match_types()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsdp="{NS_WSDP}" xmlns:wsa="{NS_WSA}" xmlns:wsd="{NS_WSD}" xmlns:pub="{NS_PUB}" xmlns:wscn="{NS_WSCN}">
  <soap:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>
    <wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
    <wsa:RelatesTo>{relates_to}</wsa:RelatesTo>
  </soap:Header>
  <soap:Body>
    <wsd:ProbeMatches>
      <wsd:ProbeMatch>
        <wsa:EndpointReference>
          <wsa:Address>{our_epr(config)}</wsa:Address>
        </wsa:EndpointReference>
        <wsd:Types>{types}</wsd:Types>
        <wsd:XAddrs>{xaddr}</wsd:XAddrs>
        <wsd:MetadataVersion>{meta}</wsd:MetadataVersion>
      </wsd:ProbeMatch>
    </wsd:ProbeMatches>
  </soap:Body>
</soap:Envelope>
"""


def build_resolve_matches(
    config: Config,
    relates_to: str,
    xaddr: str,
    outbound_message_id: str | None = None,
) -> str:
    """Build ResolveMatches response payload."""
    mid = outbound_message_id or _new_message_id()
    meta = getattr(config, "metadata_version", 1)
    types = _probe_match_types()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsdp="{NS_WSDP}" xmlns:wsa="{NS_WSA}" xmlns:wsd="{NS_WSD}" xmlns:pub="{NS_PUB}" xmlns:wscn="{NS_WSCN}">
  <soap:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ResolveMatches</wsa:Action>
    <wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
    <wsa:RelatesTo>{relates_to}</wsa:RelatesTo>
  </soap:Header>
  <soap:Body>
    <wsd:ResolveMatches>
      <wsd:ResolveMatch>
        <wsa:EndpointReference>
          <wsa:Address>{our_epr(config)}</wsa:Address>
        </wsa:EndpointReference>
        <wsd:Types>{types}</wsd:Types>
        <wsd:XAddrs>{xaddr}</wsd:XAddrs>
        <wsd:MetadataVersion>{meta}</wsd:MetadataVersion>
      </wsd:ResolveMatch>
    </wsd:ResolveMatches>
  </soap:Body>
</soap:Envelope>
"""


def _normalize_epr(s: str) -> str:
    return s.strip().lower()


def _epr_matches_ours(config: Config, remote_epr: str) -> bool:
    return _normalize_epr(remote_epr) == _normalize_epr(our_epr(config))


def _remember_outbound_probe_id(message_id: str, now: float | None = None) -> None:
    ts = time.monotonic() if now is None else now
    _prune_recent_outbound_probe_ids(now=ts)
    _recent_outbound_probe_ids[message_id] = ts + SELF_PROBE_TTL_SEC
    if len(_recent_outbound_probe_ids) > SELF_PROBE_CACHE_MAX:
        oldest_id, _ = min(_recent_outbound_probe_ids.items(), key=lambda entry: entry[1])
        _recent_outbound_probe_ids.pop(oldest_id, None)


def _is_recent_outbound_probe_id(message_id: str, now: float | None = None) -> bool:
    ts = time.monotonic() if now is None else now
    _prune_recent_outbound_probe_ids(now=ts)
    expiry = _recent_outbound_probe_ids.get(message_id)
    return expiry is not None and expiry > ts


def _prune_recent_outbound_probe_ids(now: float | None = None) -> None:
    ts = time.monotonic() if now is None else now
    expired = [mid for mid, expiry in _recent_outbound_probe_ids.items() if expiry <= ts]
    for mid in expired:
        _recent_outbound_probe_ids.pop(mid, None)


def configure_multicast_interface(sock: socket.socket, advertise_addr: str) -> None:
    if not advertise_addr or advertise_addr in ("0.0.0.0", "127.0.0.1"):
        return
    try:
        packed = socket.inet_aton(advertise_addr)
    except OSError:
        log.warning(
            "Skipping IP_MULTICAST_IF; advertise_addr is not IPv4",
            extra={"advertise_addr": advertise_addr},
        )
        return
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, packed)
    except OSError as e:
        log.warning(
            "IP_MULTICAST_IF failed",
            extra={"advertise_addr": advertise_addr, "error": str(e)},
        )


def handle_discovery_packet(
    config: Config,
    data: bytes,
    addr: tuple[str, int],
    sock: socket.socket,
) -> bool:
    """Handle a single multicast discovery packet."""
    text = data.decode(errors="ignore")
    action = extract_action(text)
    message_id = extract_message_id(text)
    ingress_level = logging.DEBUG if _is_recent_outbound_probe_id(message_id) else logging.INFO
    log.log(
        ingress_level,
        "Discovery packet received",
        extra={
            "addr": str(addr),
            "bytes": len(data),
            "action": action,
            "message_id": message_id,
        },
    )
    if not action:
        log.warning(
            "Invalid discovery packet (missing Action)",
            extra={"addr": str(addr), "bytes": len(data), "message_id": message_id},
        )
        return False

    xaddr = build_xaddr(config)

    if action == ACTION_PROBE:
        relates_to = extract_message_id(text)
        if _is_recent_outbound_probe_id(relates_to):
            log.debug(
                "Probe ignored by self-filter policy",
                extra={"addr": str(addr), "message_id": relates_to, "policy": "message_id_ttl"},
            )
            return False
        response = build_probe_match(config, relates_to, xaddr)
        sock.sendto(response.encode("utf-8"), addr)
        log.info(
            "ProbeMatch sent",
            extra={"addr": str(addr), "relates_to": relates_to, "xaddr": xaddr},
        )
        log.info("Probe received", extra={"addr": str(addr)})
        return True

    if action == ACTION_RESOLVE:
        target = extract_resolve_epr_address(text)
        if target is None:
            log.warning("Invalid Resolve packet (no EPR in body)", extra={"addr": str(addr)})
            return False
        if not _epr_matches_ours(config, target):
            log.info(
                "Resolve ignored (EPR mismatch)",
                extra={"addr": str(addr), "target": target},
            )
            return False
        relates_to = extract_message_id(text)
        response = build_resolve_matches(config, relates_to, xaddr)
        sock.sendto(response.encode("utf-8"), addr)
        log.info(
            "ResolveMatch sent",
            extra={"addr": str(addr), "relates_to": relates_to, "xaddr": xaddr},
        )
        log.info("Resolve received", extra={"addr": str(addr)})
        return True

    if action in (ACTION_HELLO, ACTION_BYE):
        log.debug(
            "Unsolicited discovery message observed",
            extra={"addr": str(addr), "action": action, "message_id": message_id},
        )
        return False

    unsupported_level = (
        logging.DEBUG if _is_recent_outbound_probe_id(message_id) else logging.WARNING
    )
    log.log(
        unsupported_level,
        "Unsupported discovery action",
        extra={"addr": str(addr), "action": action, "message_id": message_id},
    )
    return False


def _build_ws_discovery_client_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 0))
    return sock


async def _recv_discovery_match(
    sock: socket.socket, timeout_sec: float
) -> tuple[str, str, list[str]] | None:
    loop = asyncio.get_running_loop()
    try:
        data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 8192), timeout=timeout_sec)
    except asyncio.TimeoutError:
        return None
    text = data.decode(errors="ignore")
    action = extract_action(text)
    relates_to = extract_relates_to(text)
    message_id = extract_message_id(text)
    xaddrs = extract_xaddrs(text)
    ingress_level = (
        logging.DEBUG if _is_recent_outbound_probe_id(relates_to or "") else logging.INFO
    )
    log.log(
        ingress_level,
        "Discovery match packet received",
        extra={
            "addr": str(addr),
            "bytes": len(data),
            "action": action,
            "message_id": message_id,
            "relates_to": relates_to,
            "xaddrs_count": len(xaddrs),
        },
    )
    if not action or not relates_to:
        log.warning(
            "Invalid discovery match packet",
            extra={
                "addr": str(addr),
                "bytes": len(data),
                "action": action,
                "message_id": message_id,
                "relates_to": relates_to,
            },
        )
        return None
    return action, relates_to, xaddrs


async def discover_scanner_xaddr(
    config: Config,
    *,
    timeout_sec: float = 2.0,
    max_attempts: int = 3,
) -> str | None:
    """Actively probe multicast and return first scanner XAddr found."""
    if getattr(config, "scanner_xaddr", ""):
        return config.scanner_xaddr

    sock = _build_ws_discovery_client_socket()
    configure_multicast_interface(sock, config.advertise_addr)
    sock.setblocking(False)

    try:
        loop = asyncio.get_running_loop()
        for _ in range(max_attempts):
            probe_mid, probe_xml = build_probe()
            _remember_outbound_probe_id(probe_mid)
            log.info("Discovery Probe sent", extra={"probe_message_id": probe_mid})
            await loop.sock_sendto(sock, probe_xml.encode("utf-8"), (MULTICAST_GROUP, PORT))

            deadline = loop.time() + timeout_sec
            while loop.time() < deadline:
                remaining = deadline - loop.time()
                match = await _recv_discovery_match(sock, remaining)
                if match is None:
                    break
                action, relates_to, xaddrs = match
                if action == ACTION_PROBE_MATCHES and relates_to == probe_mid and xaddrs:
                    log.info(
                        "Scanner XAddr discovered",
                        extra={"probe_message_id": probe_mid, "scanner_xaddr": xaddrs[0]},
                    )
                    return xaddrs[0]
                if action == ACTION_PROBE_MATCHES and relates_to == probe_mid and not xaddrs:
                    log.warning(
                        "ProbeMatches missing XAddrs",
                        extra={"probe_message_id": probe_mid},
                    )
                else:
                    level = (
                        logging.DEBUG if _is_recent_outbound_probe_id(relates_to) else logging.INFO
                    )
                    log.log(
                        level,
                        "Discovery match ignored",
                        extra={
                            "probe_message_id": probe_mid,
                            "action": action,
                            "relates_to": relates_to,
                        },
                    )
    finally:
        sock.close()

    return None


async def _send_hello(sock: socket.socket, config: Config, message_number: int) -> None:
    """Send one multicast Hello frame."""
    loop = asyncio.get_running_loop()
    body = build_hello(config, message_number).encode("utf-8")
    await loop.sock_sendto(sock, body, (MULTICAST_GROUP, PORT))
    setattr(config, "discovery_last_message_number", message_number)
    log.info(
        "Hello multicast sent",
        extra={"n": message_number, "xaddr": build_xaddr(config)},
    )


async def _send_bye(sock: socket.socket, config: Config, message_number: int) -> None:
    """Send one multicast Bye frame."""
    loop = asyncio.get_running_loop()
    body = build_bye(config, message_number).encode("utf-8")
    await loop.sock_sendto(sock, body, (MULTICAST_GROUP, PORT))
    log.info(
        "Bye multicast sent",
        extra={"n": message_number, "xaddr": build_xaddr(config)},
    )


async def _hello_sender(sock: socket.socket, config: Config) -> None:
    """Continuously emit Hello messages at configured interval."""
    n = 0
    interval = float(getattr(config, "hello_interval_sec", 60.0))
    await _send_hello(sock, config, n)
    n += 1
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        await _send_hello(sock, config, n)
        n += 1


async def start_discovery(config: Config) -> None:
    """Start WS-Discovery listener loop and periodic Hello sender."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", PORT))

    mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton("0.0.0.0")
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    configure_multicast_interface(sock, config.advertise_addr)
    sock.setblocking(False)

    log.info("WSD discovery listening")

    loop = asyncio.get_running_loop()
    hello_task = asyncio.create_task(_hello_sender(sock, config))

    try:
        while True:
            data, addr = await loop.sock_recvfrom(sock, 8192)
            handle_discovery_packet(config, data, addr, sock)
    except asyncio.CancelledError:
        raise
    finally:
        hello_task.cancel()
        try:
            await hello_task
        except asyncio.CancelledError:
            pass
        bye_n = int(getattr(config, "discovery_last_message_number", -1)) + 1
        try:
            await _send_bye(sock, config, bye_n)
        except Exception:
            log.exception("WS-Discovery Bye send failed during shutdown")
        sock.close()

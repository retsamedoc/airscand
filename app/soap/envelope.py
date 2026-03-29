"""SOAP 1.2 envelope construction for outbound client requests and inbound responses."""

from __future__ import annotations

from app.soap.addressing import new_message_id
from app.soap.namespaces import (
    NS_PUB,
    NS_SCA,
    NS_SOAP,
    NS_WSA,
    NS_WSCN,
    NS_WSD,
    NS_WSDP,
    NS_WSE,
    NS_WSMAN,
    WSA_ANONYMOUS,
)


def _xmlns_attr(extra: dict[str, str]) -> str:
    """Build ``xmlns:...`` declarations: soap, wsa, then extra prefixes sorted."""
    parts = [f'xmlns:soap="{NS_SOAP}"', f'xmlns:wsa="{NS_WSA}"']
    for prefix in sorted(extra.keys()):
        parts.append(f'xmlns:{prefix}="{extra[prefix]}"')
    return " ".join(parts)


def build_outbound_client_envelope(
    *,
    xmlns_extra: dict[str, str],
    action: str,
    to_url: str,
    body_inner_xml: str,
    message_id: str | None = None,
    from_address: str | None = None,
    reply_to_anonymous: bool = True,
    between_to_and_message_id: str = "",
) -> tuple[str, str]:
    """Build standard outbound SOAP envelope with WS-A 2004/08 headers.

    Header order: Action, To, optional fragment between To and MessageID, MessageID,
    optional From, optional ReplyTo anonymous.
    """
    mid = message_id or new_message_id()
    from_line = (
        f"""    <wsa:From>
      <wsa:Address>{from_address}</wsa:Address>
    </wsa:From>
"""
        if from_address
        else ""
    )
    reply_block = ""
    if reply_to_anonymous:
        reply_block = f"""    <wsa:ReplyTo>
      <wsa:Address>{WSA_ANONYMOUS}</wsa:Address>
    </wsa:ReplyTo>
"""
    xml_ns = _xmlns_attr(xmlns_extra)
    if not body_inner_xml.strip():
        body_block = "  <soap:Body/>"
    else:
        body_block = f"""  <soap:Body>
{body_inner_xml}
  </soap:Body>"""
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope {xml_ns}>
  <soap:Header>
    <wsa:Action>{action}</wsa:Action>
    <wsa:To>{to_url}</wsa:To>
{between_to_and_message_id}    <wsa:MessageID>{mid}</wsa:MessageID>
{from_line}{reply_block}  </soap:Header>
{body_block}
</soap:Envelope>
"""
    return mid, body


def build_inbound_response_envelope(
    *,
    action: str,
    relates_to: str | None,
    body_xml: str = "",
    outbound_message_id: str | None = None,
) -> str:
    """Build SOAP response envelope with To=anonymous and optional RelatesTo (server/sink)."""
    mid = outbound_message_id or new_message_id()
    relates_line = f"    <wsa:RelatesTo>{relates_to}</wsa:RelatesTo>\n" if relates_to else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{NS_SOAP}" xmlns:wsa="{NS_WSA}" xmlns:wse="{NS_WSE}" xmlns:wsman="{NS_WSMAN}" xmlns:sca="{NS_SCA}">
  <soap:Header>
    <wsa:Action>{action}</wsa:Action>
    <wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>
    <wsa:MessageID>{mid}</wsa:MessageID>
{relates_line}  </soap:Header>
  <soap:Body>
{body_xml}
  </soap:Body>
</soap:Envelope>
"""


def build_discovery_probe_envelope(
    *,
    action: str,
    to_uri: str,
    message_id: str,
    body_inner_xml: str,
    xmlns_extra: dict[str, str],
) -> str:
    """WS-Discovery Probe/Resolve outbound: To, Action, MessageID (no ReplyTo)."""
    xml_ns = _xmlns_attr(xmlns_extra)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope {xml_ns}>
  <soap:Header>
    <wsa:To>{to_uri}</wsa:To>
    <wsa:Action>{action}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
  </soap:Header>
  <soap:Body>
{body_inner_xml}
  </soap:Body>
</soap:Envelope>
"""


def discovery_probe_xmlns() -> dict[str, str]:
    """Namespace map for outbound Probe (wsd + wscn)."""
    return {"wsd": NS_WSD, "wscn": NS_WSCN}


def discovery_hello_probematch_xmlns() -> dict[str, str]:
    """Namespaces for Hello / ProbeMatches / ResolveMatches (wsdp, pub, wscn)."""
    return {"wsdp": NS_WSDP, "pub": NS_PUB, "wscn": NS_WSCN}

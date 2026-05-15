"""SOAP fault body builders for WS-Addressing and WS-Eventing."""

from __future__ import annotations

from app.soap.envelope import build_inbound_response_envelope
from app.soap.namespaces import ACTION_WSA_FAULT, NS_WSA


def _xml_escape(text: str) -> str:
    """Escape text for inclusion inside ``soap:Text``."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def build_action_not_supported_fault_body(reason: str = "Action not supported") -> str:
    """Return a minimal SOAP 1.2 fault body for unsupported WS-A action."""
    safe = _xml_escape(reason)
    return f"""    <soap:Fault>
      <soap:Code>
        <soap:Value>soap:Sender</soap:Value>
        <soap:Subcode><soap:Value>wsa:ActionNotSupported</soap:Value></soap:Subcode>
      </soap:Code>
      <soap:Reason><soap:Text xml:lang="en">{safe}</soap:Text></soap:Reason>
      <soap:Detail>
        <wsa:ProblemAction xmlns:wsa="{NS_WSA}"/>
      </soap:Detail>
    </soap:Fault>"""


def build_ws_eventing_fault_body(*, subcode_local: str, reason: str, sender: bool = True) -> str:
    """Return SOAP 1.2 fault body with a WS-Eventing subcode (``wse:`` QName)."""
    code = "soap:Sender" if sender else "soap:Receiver"
    safe = _xml_escape(reason)
    return f"""    <soap:Fault>
      <soap:Code>
        <soap:Value>{code}</soap:Value>
        <soap:Subcode>
          <soap:Value>wse:{subcode_local}</soap:Value>
        </soap:Subcode>
      </soap:Code>
      <soap:Reason><soap:Text xml:lang="en">{safe}</soap:Text></soap:Reason>
    </soap:Fault>"""


def build_addressing_fault_envelope(*, relates_to: str | None, fault_body_inner_xml: str) -> str:
    """Wrap a SOAP fault body in an inbound response envelope with WS-A fault Action."""
    return build_inbound_response_envelope(
        action=ACTION_WSA_FAULT,
        relates_to=relates_to,
        body_xml=fault_body_inner_xml,
    )

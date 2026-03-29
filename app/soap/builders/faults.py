"""SOAP fault body builder scaffolding for future expansion."""

from __future__ import annotations

from app.soap.namespaces import NS_WSA


def build_action_not_supported_fault_body(reason: str = "Action not supported") -> str:
    """Return a minimal SOAP 1.2 fault body for unsupported WS-A action."""
    return f"""    <soap:Fault>
      <soap:Code>
        <soap:Value>soap:Sender</soap:Value>
        <soap:Subcode><soap:Value>wsa:ActionNotSupported</soap:Value></soap:Subcode>
      </soap:Code>
      <soap:Reason><soap:Text xml:lang="en">{reason}</soap:Text></soap:Reason>
      <soap:Detail>
        <wsa:ProblemAction xmlns:wsa="{NS_WSA}"/>
      </soap:Detail>
    </soap:Fault>"""

"""Shared SOAP 1.2 + WS-Addressing helpers (namespaces, envelope, transport, parsers)."""

from __future__ import annotations

from app.soap.addressing import new_message_id, soap_action_short
from app.soap.envelope import build_inbound_response_envelope, build_outbound_client_envelope
from app.soap.fault import parse_soap_fault
from app.soap.transport import SoapHttpClient, default_soap_http_client

__all__ = [
    "SoapHttpClient",
    "build_inbound_response_envelope",
    "build_outbound_client_envelope",
    "default_soap_http_client",
    "new_message_id",
    "parse_soap_fault",
    "soap_action_short",
]

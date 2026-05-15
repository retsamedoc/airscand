"""Tests for WS-Eventing ``SubscriptionEnd`` (inbound sink + manager emission)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.inbound_eventing_registry import (
    InboundSubscriptionRegistry,
    get_inbound_subscription_registry,
    reset_inbound_subscription_registry,
)
from app.inbound_subscription_end_delivery import dispatch_pending_inbound_subscription_ends
from app.soap.builders import eventing as eventing_builders
from app.soap.namespaces import (
    ACTION_SUBSCRIPTION_END,
    STATUS_SUBSCRIPTION_END_SOURCE_CANCELLING,
)
from app.soap.parsers.subscription_end import parse_inbound_subscription_end

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def _reset_inbound_subscription_registry() -> None:
    """Isolate process-wide inbound registry across tests."""
    reset_inbound_subscription_registry()
    yield
    reset_inbound_subscription_registry()


class _CaptureSoapClient:
    """Records ``post_text`` calls for manager-emitted ``SubscriptionEnd``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def post_text(self, *, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        self.calls.append((url, payload))
        return 200, ""


def test_parse_inbound_subscription_end_extracts_fields() -> None:
    """Parser reads manager identifier, status URI, and reasons."""
    soap = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wse="http://schemas.xmlsoap.org/ws/2004/08/eventing"
  xmlns:wsman="http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd">
  <soap:Body>
    <wse:SubscriptionEnd>
      <wse:SubscriptionManager>
        <wsa:Address>http://scanner/mgr</wsa:Address>
        <wsman:Identifier>urn:uuid:sub-99</wsman:Identifier>
      </wse:SubscriptionManager>
      <wse:Status>http://schemas.xmlsoap.org/ws/2004/08/eventing/SourceShuttingDown</wse:Status>
      <wse:Reason xml:lang="en">Device stopped</wse:Reason>
    </wse:SubscriptionEnd>
  </soap:Body>
</soap:Envelope>"""
    parsed = parse_inbound_subscription_end(soap)
    assert parsed is not None
    assert parsed.subscription_identifier == "urn:uuid:sub-99"
    assert parsed.status_uri == (
        "http://schemas.xmlsoap.org/ws/2004/08/eventing/SourceShuttingDown"
    )
    assert parsed.reasons == ("Device stopped",)


def test_build_subscription_end_notification_targets_endto() -> None:
    """Manager builds ``SubscriptionEnd`` with correct ``wsa:Action`` and ``wsa:To``."""
    mid, xml = eventing_builders.build_subscription_end_notification(
        subscription_end_to_address="http://peer/end",
        reference_parameters_xml=None,
        manager_address="http://self/wsd",
        subscription_identifier="urn:uuid:lease-1",
        status_uri=STATUS_SUBSCRIPTION_END_SOURCE_CANCELLING,
        reason_en="Lease lapsed",
    )
    assert mid
    assert ACTION_SUBSCRIPTION_END in xml
    assert "<wsa:To>http://peer/end</wsa:To>" in xml
    assert "urn:uuid:lease-1" in xml
    assert "http://self/wsd" in xml


def test_renew_after_lease_queues_subscription_end(monkeypatch: MonkeyPatch) -> None:
    """Expired lease on ``Renew`` removes subscription and enqueues ``SubscriptionEnd`` delivery."""
    reg = InboundSubscriptionRegistry()
    t0 = 10_000.0
    monkeypatch.setattr("app.inbound_eventing_registry.time.monotonic", lambda: t0)
    sub = reg.create(
        manager_address="http://mgr/wsd",
        granted_expires="PT1H",
        grant_seconds=60.0,
        notify_to_address="http://notify/sink",
        subscription_end_to_url="http://end/other",
        subscription_end_reference_parameters_xml=None,
    )
    monkeypatch.setattr("app.inbound_eventing_registry.time.monotonic", lambda: t0 + 120.0)
    assert (
        reg.renew(
            identifier=sub.identifier,
            manager_address="http://mgr/wsd",
            granted_expires="PT1H",
            grant_seconds=60.0,
        )
        is None
    )
    pending = reg.drain_pending_subscription_ends()
    assert len(pending) == 1
    assert pending[0].subscription_end_to_url == "http://end/other"
    assert pending[0].identifier == sub.identifier


@pytest.mark.asyncio
async def test_dispatch_pending_posts_subscription_end(monkeypatch: MonkeyPatch) -> None:
    """Drained queue results in SOAP POST to the subscriber ``EndTo`` URL."""
    reg = get_inbound_subscription_registry()
    t0 = 50_000.0
    monkeypatch.setattr("app.inbound_eventing_registry.time.monotonic", lambda: t0)
    sub = reg.create(
        manager_address="http://mgr/wsd",
        granted_expires="PT1S",
        grant_seconds=1.0,
        notify_to_address="http://notify/sink",
        subscription_end_to_url="http://end/callback",
        subscription_end_reference_parameters_xml=None,
    )
    monkeypatch.setattr("app.inbound_eventing_registry.time.monotonic", lambda: t0 + 5.0)
    reg.sweep_expired_leases()
    cap = _CaptureSoapClient()
    monkeypatch.setattr(
        "app.inbound_subscription_end_delivery.default_soap_http_client",
        lambda: cap,
    )
    await dispatch_pending_inbound_subscription_ends(timeout_sec=5.0)
    assert len(cap.calls) == 1
    url, payload = cap.calls[0]
    assert url == "http://end/callback"
    assert ACTION_SUBSCRIPTION_END in payload
    assert sub.identifier in payload

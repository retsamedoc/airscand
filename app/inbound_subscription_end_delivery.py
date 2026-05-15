"""Deliver ``SubscriptionEnd`` from inbound manager when leases lapse without ``Renew``."""

from __future__ import annotations

import logging

from app.inbound_eventing_registry import get_inbound_subscription_registry
from app.soap.builders import eventing as eventing_builders
from app.soap.namespaces import STATUS_SUBSCRIPTION_END_SOURCE_CANCELLING
from app.soap.transport import default_soap_http_client

log = logging.getLogger(__name__)

__all__ = ["dispatch_pending_inbound_subscription_ends"]


async def dispatch_pending_inbound_subscription_ends(*, timeout_sec: float) -> None:
    """POST queued ``SubscriptionEnd`` notifications (best-effort; failures are logged).

    When the inbound subscription manager removes an expired lease, it enqueues one row per
    subscription so the subscriber's ``EndTo`` (or ``NotifyTo`` when ``EndTo`` is absent)
    receives a standards-shaped teardown signal per WS-Eventing.

    Args:
        timeout_sec: HTTP read/connect budget forwarded to :class:`~app.soap.transport.SoapHttpClient`.
    """
    reg = get_inbound_subscription_registry()
    pending = reg.drain_pending_subscription_ends()
    if not pending:
        return
    client = default_soap_http_client()
    for due in pending:
        _msg_id, payload = eventing_builders.build_subscription_end_notification(
            subscription_end_to_address=due.subscription_end_to_url,
            reference_parameters_xml=due.subscription_end_reference_parameters_xml,
            manager_address=due.manager_address,
            subscription_identifier=due.identifier,
            status_uri=STATUS_SUBSCRIPTION_END_SOURCE_CANCELLING,
            reason_en="Subscription lease expired at manager without Renew",
        )
        try:
            status, _body = await client.post_text(
                url=due.subscription_end_to_url,
                payload=payload,
                timeout_sec=timeout_sec,
            )
            log.info(
                "Sent SubscriptionEnd to subscriber",
                extra={
                    "subscription_end_to": due.subscription_end_to_url,
                    "subscription_id": due.identifier,
                    "http_status": status,
                },
            )
        except Exception:
            log.exception(
                "SubscriptionEnd delivery failed",
                extra={"subscription_end_to": due.subscription_end_to_url},
            )

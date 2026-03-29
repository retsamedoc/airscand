"""WS-Eventing outbound SOAP builders (body XML + envelope shell)."""

from __future__ import annotations

from app.destinations import DEFAULT_DESTINATIONS, subscribe_tuple_destinations
from app.soap.addressing import new_message_id
from app.soap.envelope import build_outbound_client_envelope
from app.soap.namespaces import (
    ACTION_RENEW,
    ACTION_SUBSCRIBE,
    ACTION_UNSUBSCRIBE,
    FILTER_DIALECT_DEVPROF_ACTION,
    NS_SCA,
    NS_WSE,
    SCAN_AVAILABLE_EVENT_ACTION,
)
from app.soap.parsers.eventing import effective_subscription_identifier_for_unsubscribe

DEFAULT_SCAN_DESTINATIONS = subscribe_tuple_destinations(DEFAULT_DESTINATIONS)


def build_subscribe_request(
    *,
    notify_to: str,
    to_url: str,
    from_address: str | None = None,
    subscription_identifier: str | None = None,
    filter_action: str = SCAN_AVAILABLE_EVENT_ACTION,
    scan_destinations: tuple[tuple[str, str], ...] = DEFAULT_SCAN_DESTINATIONS,
    message_id: str | None = None,
) -> tuple[str, str]:
    """Build WS-Eventing Subscribe SOAP envelope."""
    sub_id = subscription_identifier or new_message_id()
    ref_params = f"""          <wsa:ReferenceParameters>
            <wse:Identifier>{sub_id}</wse:Identifier>
          </wsa:ReferenceParameters>
"""
    destinations_xml = "".join(
        f"""        <sca:ScanDestination>
          <sca:ClientDisplayName>{display_name}</sca:ClientDisplayName>
          <sca:ClientContext>{client_context}</sca:ClientContext>
        </sca:ScanDestination>
"""
        for display_name, client_context in scan_destinations
    )
    body_inner = f"""    <wse:Subscribe>
      <wse:EndTo>
        <wsa:Address>{notify_to}</wsa:Address>
{ref_params}      </wse:EndTo>
      <wse:Delivery Mode="http://schemas.xmlsoap.org/ws/2004/08/eventing/DeliveryModes/Push">
        <wse:NotifyTo>
          <wsa:Address>{notify_to}</wsa:Address>
{ref_params}        </wse:NotifyTo>
      </wse:Delivery>
      <wse:Filter Dialect="{FILTER_DIALECT_DEVPROF_ACTION}">{filter_action}</wse:Filter>
      <sca:ScanDestinations>
{destinations_xml}      </sca:ScanDestinations>
      <wse:Expires>PT1H</wse:Expires>
    </wse:Subscribe>"""
    return build_outbound_client_envelope(
        xmlns_extra={"wse": NS_WSE, "sca": NS_SCA},
        action=ACTION_SUBSCRIBE,
        to_url=to_url,
        body_inner_xml=body_inner,
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id="",
    )


def build_renew_request(
    *,
    to_url: str,
    subscription_identifier: str = "",
    reference_parameters_xml: str | None = None,
    from_address: str | None = None,
    requested_expires: str = "PT1H",
    message_id: str | None = None,
) -> tuple[str, str]:
    """Build WS-Eventing Renew SOAP envelope for the subscription manager endpoint."""
    addr = (to_url or "").strip()
    eff_id = effective_subscription_identifier_for_unsubscribe(
        subscription_identifier,
        reference_parameters_xml,
    )
    id_line = f"    <wse:Identifier>{eff_id}</wse:Identifier>\n" if eff_id else ""
    body_inner = f"""    <wse:Renew>
      <wse:Expires>{requested_expires}</wse:Expires>
    </wse:Renew>
"""
    return build_outbound_client_envelope(
        xmlns_extra={"wse": NS_WSE},
        action=ACTION_RENEW,
        to_url=addr,
        body_inner_xml=body_inner,
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id=id_line,
    )


def build_unsubscribe_request(
    *,
    to_url: str,
    subscription_identifier: str = "",
    reference_parameters_xml: str | None = None,
    from_address: str | None = None,
    message_id: str | None = None,
) -> tuple[str, str]:
    """Build WS-Eventing Unsubscribe SOAP envelope for the subscription manager endpoint."""
    addr = (to_url or "").strip()
    eff_id = effective_subscription_identifier_for_unsubscribe(
        subscription_identifier,
        reference_parameters_xml,
    )
    id_line = f"    <wse:Identifier>{eff_id}</wse:Identifier>\n" if eff_id else ""
    body_inner = "    <wse:Unsubscribe/>\n"
    return build_outbound_client_envelope(
        xmlns_extra={"wse": NS_WSE},
        action=ACTION_UNSUBSCRIBE,
        to_url=addr,
        body_inner_xml=body_inner,
        message_id=message_id,
        from_address=from_address,
        reply_to_anonymous=True,
        between_to_and_message_id=id_line,
    )

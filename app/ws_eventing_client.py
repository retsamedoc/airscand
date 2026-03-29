"""Outbound WS-Eventing and WS-Transfer client helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from pathlib import Path

from aiohttp import ClientError

from app.destinations import DEFAULT_DESTINATIONS, ScanDestination, lookup_destination
from app.mtom import parse_retrieve_image_mtom
from app.quirks import ScannerProfile
from app.scan_storage import save_scan_file
from app.scanner_status_coordination import (
    await_scanner_idle_after_retrieve,
    begin_retrieve_idle_wait,
    end_retrieve_idle_wait,
)
from app.soap import namespaces
from app.soap.builders import eventing as eventing_builders
from app.soap.fault import parse_soap_fault
from app.soap.parsers import capabilities as scanner_capabilities
from app.soap.parsers import eventing as eventing_parsers
from app.soap.parsers import scan as scan_parsers
from app.soap.parsers import transfer as transfer_parsers

parse_scanner_capabilities = scanner_capabilities.parse_scanner_capabilities
# Re-export for callers/tests.
InputSourceCapabilities = scanner_capabilities.InputSourceCapabilities
ScannerCapabilities = scanner_capabilities.ScannerCapabilities
from app.soap.transport import default_soap_http_client

# Re-export namespace constants for tests and main (explicit aliases satisfy static analysis).
ACTION_CREATE_SCAN_JOB = namespaces.ACTION_CREATE_SCAN_JOB
ACTION_GET = namespaces.ACTION_GET
ACTION_GET_JOB_STATUS = namespaces.ACTION_GET_JOB_STATUS
ACTION_GET_SCANNER_ELEMENTS = namespaces.ACTION_GET_SCANNER_ELEMENTS
ACTION_RETRIEVE_IMAGE = namespaces.ACTION_RETRIEVE_IMAGE
ACTION_RENEW = namespaces.ACTION_RENEW
ACTION_SUBSCRIBE = namespaces.ACTION_SUBSCRIBE
ACTION_UNSUBSCRIBE = namespaces.ACTION_UNSUBSCRIBE
ACTION_VALIDATE_SCAN_TICKET = namespaces.ACTION_VALIDATE_SCAN_TICKET
FILTER_DIALECT_DEVPROF_ACTION = namespaces.FILTER_DIALECT_DEVPROF_ACTION
NS_SOAP = namespaces.NS_SOAP
NS_SCA = namespaces.NS_SCA
NS_WSA = namespaces.NS_WSA
NS_WSE = namespaces.NS_WSE
NS_WSMAN = namespaces.NS_WSMAN
NS_WST = namespaces.NS_WST
SCAN_AVAILABLE_EVENT_ACTION = namespaces.SCAN_AVAILABLE_EVENT_ACTION
SCANNER_STATUS_SUMMARY_EVENT_ACTION = namespaces.SCANNER_STATUS_SUMMARY_EVENT_ACTION
WSA_ANONYMOUS = namespaces.WSA_ANONYMOUS

DEFAULT_DOCUMENT_NUMBER = scan_parsers.DEFAULT_DOCUMENT_NUMBER
INVALID_DESTINATION_TOKEN_FAULT = scan_parsers.INVALID_DESTINATION_TOKEN_FAULT
GET_JOB_STATUS_INITIAL_INTERVAL_SEC = scan_parsers.GET_JOB_STATUS_INITIAL_INTERVAL_SEC
GET_JOB_STATUS_MAX_INTERVAL_SEC = scan_parsers.GET_JOB_STATUS_MAX_INTERVAL_SEC
GET_JOB_STATUS_MAX_WAIT_SEC = scan_parsers.GET_JOB_STATUS_MAX_WAIT_SEC
SCANNER_METADATA_ELEMENT_PREFIX = scan_parsers.SCANNER_METADATA_ELEMENT_PREFIX
SCANNER_METADATA_ELEMENT_NAMES = scan_parsers.SCANNER_METADATA_ELEMENT_NAMES
SCANNER_METADATA_ELEMENT_NAMES_NO_DEFAULT_TICKET = (
    scan_parsers.SCANNER_METADATA_ELEMENT_NAMES_NO_DEFAULT_TICKET
)
DEFAULT_SCAN_DESTINATIONS = eventing_builders.DEFAULT_SCAN_DESTINATIONS
SCAN_TICKET_TEMPLATE_XML = scan_parsers.SCAN_TICKET_TEMPLATE_XML

build_renew_request = eventing_builders.build_renew_request
build_subscribe_request = eventing_builders.build_subscribe_request
build_unsubscribe_request = eventing_builders.build_unsubscribe_request
build_get_request = transfer_parsers.build_get_request
build_validate_scan_ticket_request = scan_parsers.build_validate_scan_ticket_request
build_create_scan_job_request = scan_parsers.build_create_scan_job_request
build_retrieve_image_request = scan_parsers.build_retrieve_image_request
build_get_job_status_request = scan_parsers.build_get_job_status_request
build_get_scanner_elements_request = scan_parsers.build_get_scanner_elements_request
extract_subscribe_destination_tokens_by_client_context = (
    eventing_parsers.extract_subscribe_destination_tokens_by_client_context
)
extract_subscribe_destination_token = eventing_parsers.extract_subscribe_destination_token
extract_subscription_manager_epr = eventing_parsers.extract_subscription_manager_epr
extract_subscription_manager_url = eventing_parsers.extract_subscription_manager_url
parse_iso8601_duration_to_seconds = eventing_parsers.parse_iso8601_duration_to_seconds
parse_renew_response = eventing_parsers.parse_renew_response
parse_subscribe_response = eventing_parsers.parse_subscribe_response
parse_get_response = transfer_parsers.parse_get_response
parse_validate_scan_ticket_response = scan_parsers.parse_validate_scan_ticket_response
parse_create_scan_job_response = scan_parsers.parse_create_scan_job_response
parse_get_job_status_response = scan_parsers.parse_get_job_status_response
parse_retrieve_image_response = scan_parsers.parse_retrieve_image_response
parse_scanner_status_summary_event = scan_parsers.parse_scanner_status_summary_event
parse_get_scanner_elements_response = scan_parsers.parse_get_scanner_elements_response
build_scan_ticket_from_destination_config = scan_parsers.build_scan_ticket_from_destination_config
validate_scan_ticket_against_capabilities = scan_parsers.validate_scan_ticket_against_capabilities
apply_scanner_configuration_to_scan_ticket_xml = (
    scan_parsers.apply_scanner_configuration_to_scan_ticket_xml
)
resolve_scan_ticket_xml_for_chain = scan_parsers.resolve_scan_ticket_xml_for_chain
resolve_wdp_scan_url = scan_parsers.resolve_wdp_scan_url
extract_destination_token = scan_parsers.extract_destination_token
extract_client_context = scan_parsers.extract_client_context
resolve_subscribe_destination_token_for_chain = (
    scan_parsers.resolve_subscribe_destination_token_for_chain
)
extract_soap_envelope_message_id = scan_parsers.extract_soap_envelope_message_id
extract_scan_identifier = scan_parsers.extract_scan_identifier
extract_event_subscription_identifier = scan_parsers.extract_event_subscription_identifier

_effective_subscription_identifier_for_unsubscribe = (
    eventing_parsers.effective_subscription_identifier_for_unsubscribe
)

log = logging.getLogger(__name__)


async def _post_soap(
    *,
    url: str,
    payload: str,
    timeout_sec: float,
) -> tuple[int, str]:
    """POST SOAP payload and return status and response text."""
    return await default_soap_http_client().post_text(
        url=url, payload=payload, timeout_sec=timeout_sec
    )


async def _post_soap_retrieve_image(
    *,
    url: str,
    payload: str,
    timeout_sec: float,
) -> tuple[int, bytes, str | None]:
    """POST SOAP payload and return status, raw response body, and response Content-Type."""
    return await default_soap_http_client().post_retrieve_image(
        url=url, payload=payload, timeout_sec=timeout_sec
    )


async def poll_get_job_status_until_ready(
    *,
    target_url: str,
    job_id: str,
    job_token: str,
    from_address: str | None,
    timeout_sec: float,
    max_wait_sec: float = GET_JOB_STATUS_MAX_WAIT_SEC,
    enabled: bool = True,
) -> dict[str, object]:
    """Poll GetJobStatus until the job is ready for RetrieveImage or timeout (WIA §7.3)."""
    if not enabled:
        return {
            "skipped": True,
            "polls": 0,
            "last_job_state": None,
            "timed_out": False,
            "unsupported": False,
            "terminal_failure": False,
        }

    deadline = time.monotonic() + max_wait_sec
    await asyncio.sleep(GET_JOB_STATUS_INITIAL_INTERVAL_SEC)
    interval = GET_JOB_STATUS_INITIAL_INTERVAL_SEC
    polls = 0
    last_state: str | None = None
    last_images: str | None = None

    while time.monotonic() <= deadline:
        polls += 1
        _mid, payload = scan_parsers.build_get_job_status_request(
            to_url=target_url,
            job_id=job_id,
            job_token=job_token,
            from_address=from_address,
        )
        status, response_text = await _post_soap(
            url=target_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        details = scan_parsers.parse_get_job_status_response(response_text)
        last_state = details.get("job_state")
        last_images = details.get("images_to_transfer")
        if polls == 1 and scan_parsers.get_job_status_fault_implies_unsupported(status, details):
            log.info(
                "GetJobStatus not supported or failed; continuing without status polling",
                extra={
                    "target_url": target_url,
                    "http_status": status,
                    "fault_subcode": details.get("fault_subcode"),
                },
            )
            return {
                "skipped": True,
                "polls": polls,
                "last_job_state": last_state,
                "timed_out": False,
                "unsupported": True,
                "terminal_failure": False,
            }
        if status < 200 or status >= 300:
            log.warning(
                "GetJobStatus returned non-success HTTP status",
                extra={"target_url": target_url, "http_status": status},
            )
            if polls == 1:
                return {
                    "skipped": True,
                    "polls": polls,
                    "last_job_state": last_state,
                    "timed_out": False,
                    "unsupported": True,
                    "terminal_failure": False,
                }
            break
        if details.get("fault_code") and not details.get("job_state"):
            log.warning(
                "GetJobStatus SOAP fault without JobState",
                extra={
                    "target_url": target_url,
                    "fault_subcode": details.get("fault_subcode"),
                },
            )
            if polls == 1:
                return {
                    "skipped": True,
                    "polls": polls,
                    "last_job_state": last_state,
                    "timed_out": False,
                    "unsupported": False,
                    "terminal_failure": False,
                }
            break
        if scan_parsers.job_status_terminal_failure(last_state):
            log.warning(
                "GetJobStatus terminal job state",
                extra={"target_url": target_url, "job_state": last_state},
            )
            return {
                "skipped": False,
                "polls": polls,
                "last_job_state": last_state,
                "timed_out": False,
                "unsupported": False,
                "terminal_failure": True,
            }
        if scan_parsers.job_ready_for_retrieve_from_status(last_state, last_images):
            log.info(
                "GetJobStatus indicates job ready for RetrieveImage",
                extra={
                    "target_url": target_url,
                    "polls": polls,
                    "job_state": last_state,
                    "images_to_transfer": last_images,
                },
            )
            return {
                "skipped": False,
                "polls": polls,
                "last_job_state": last_state,
                "timed_out": False,
                "unsupported": False,
                "terminal_failure": False,
            }
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, GET_JOB_STATUS_MAX_INTERVAL_SEC)

    log.warning(
        "GetJobStatus polling timed out before ready state; attempting RetrieveImage anyway",
        extra={
            "target_url": target_url,
            "polls": polls,
            "last_job_state": last_state,
        },
    )
    return {
        "skipped": False,
        "polls": polls,
        "last_job_state": last_state,
        "timed_out": True,
        "unsupported": False,
        "terminal_failure": False,
    }


async def preflight_get_scanner_capabilities(
    *,
    scanner_xaddr: str,
    timeout_sec: float = 5.0,
    get_to_url: str | None = None,
    from_address: str | None = None,
) -> dict[str, str | None]:
    """Query scanner capabilities and parse helpful endpoint hints."""
    get_url = get_to_url or scanner_xaddr
    message_id, payload = transfer_parsers.build_get_request(
        to_url=get_url, from_address=from_address
    )
    log.info(
        "Outbound WS-Transfer Get sending",
        extra={
            "scanner_xaddr": scanner_xaddr,
            "get_to_url": get_url,
            "get_message_id": message_id,
            "timeout_sec": timeout_sec,
        },
    )
    try:
        status, response_text = await _post_soap(
            url=get_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        details = transfer_parsers.parse_get_response(response_text)
        details.update(parse_soap_fault(response_text))
        details.update({"status": str(status), "message_id": message_id})
        if status < 200 or status >= 300:
            log.warning(
                "Outbound WS-Transfer Get returned non-success status",
                extra={
                    "scanner_xaddr": scanner_xaddr,
                    "get_to_url": get_url,
                    "status": status,
                    "fault_subcode": details["fault_subcode"],
                    "fault_reason": details["fault_reason"],
                },
            )
        log.info(
            "Outbound WS-Transfer Get completed",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "get_to_url": get_url,
                "status": status,
                "get_message_id": message_id,
                "suggested_subscribe_to_url": details["suggested_subscribe_to_url"],
            },
        )
        return details
    except asyncio.TimeoutError:
        log.warning(
            "Outbound WS-Transfer Get timed out",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "get_to_url": get_url,
                "timeout_sec": timeout_sec,
            },
        )
        raise
    except ClientError as exc:
        log.warning(
            "Outbound WS-Transfer Get transport error",
            extra={"scanner_xaddr": scanner_xaddr, "get_to_url": get_url, "error": str(exc)},
        )
        raise


async def register_with_scanner(
    *,
    scanner_xaddr: str,
    notify_to: str,
    timeout_sec: float = 5.0,
    subscribe_to_url: str | None = None,
    from_address: str | None = None,
    subscription_identifier: str | None = None,
    filter_action: str = SCAN_AVAILABLE_EVENT_ACTION,
    scan_destinations: tuple[tuple[str, str], ...] = DEFAULT_SCAN_DESTINATIONS,
) -> dict[str, str | None]:
    """Send WS-Eventing Subscribe request to scanner endpoint."""
    to_url = subscribe_to_url or scanner_xaddr
    message_id, payload = eventing_builders.build_subscribe_request(
        notify_to=notify_to,
        to_url=to_url,
        from_address=from_address,
        subscription_identifier=subscription_identifier,
        filter_action=filter_action,
        scan_destinations=scan_destinations,
    )
    log.info(
        "Outbound WS-Eventing subscribe sending",
        extra={
            "scanner_xaddr": scanner_xaddr,
            "subscribe_to_url": to_url,
            "notify_to": notify_to,
            "message_id": message_id,
            "timeout_sec": timeout_sec,
        },
    )

    try:
        status, response_text = await _post_soap(
            url=to_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        details = eventing_parsers.parse_subscribe_response(response_text)
        details.update(parse_soap_fault(response_text))
        details.update({"status": str(status), "message_id": message_id})
        if status < 200 or status >= 300:
            log.warning(
                "Outbound WS-Eventing subscribe returned non-success status",
                extra={
                    "scanner_xaddr": scanner_xaddr,
                    "subscribe_to_url": to_url,
                    "status": status,
                    "fault_subcode": details["fault_subcode"],
                    "fault_reason": details["fault_reason"],
                },
            )
        if not details["identifier"]:
            log.warning(
                "Outbound WS-Eventing subscribe response missing Identifier",
                extra={
                    "scanner_xaddr": scanner_xaddr,
                    "subscribe_to_url": to_url,
                    "status": status,
                },
            )
        log.info(
            "Outbound WS-Eventing subscribe completed",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "subscribe_to_url": to_url,
                "notify_to": notify_to,
                "status": status,
                "subscription_id": details["identifier"],
                "subscribe_destination_token": details.get("subscribe_destination_token"),
                "expires": details["expires"],
                "fault_subcode": details["fault_subcode"],
                "subscribe_message_id": message_id,
            },
        )
        return details
    except asyncio.TimeoutError:
        log.warning(
            "Outbound WS-Eventing subscribe timed out",
            extra={"scanner_xaddr": scanner_xaddr, "timeout_sec": timeout_sec},
        )
        raise
    except ClientError as exc:
        log.warning(
            "Outbound WS-Eventing subscribe transport error",
            extra={"scanner_xaddr": scanner_xaddr, "error": str(exc)},
        )
        raise


async def unsubscribe_from_scanner(
    *,
    manager_url: str,
    subscription_id: str = "",
    reference_parameters_xml: str | None = None,
    from_address: str | None = None,
    timeout_sec: float = 5.0,
) -> dict[str, str | None]:
    """Send WS-Eventing Unsubscribe to the subscription manager endpoint."""
    trimmed_url = (manager_url or "").strip()
    trimmed_id = (subscription_id or "").strip()
    if not trimmed_url:
        log.info(
            "Skipping WS-Eventing unsubscribe (missing subscription manager URL from SubscribeResponse)",
            extra={
                "subscription_manager_url": trimmed_url,
                "subscription_id": trimmed_id,
            },
        )
        return {
            "status": "skipped",
            "message_id": None,
            "fault_code": None,
            "fault_subcode": None,
            "fault_reason": None,
        }
    eff_id = _effective_subscription_identifier_for_unsubscribe(
        trimmed_id,
        reference_parameters_xml if reference_parameters_xml else None,
    )
    if not eff_id:
        log.info(
            "Skipping WS-Eventing unsubscribe (cannot resolve subscription identifier)",
            extra={
                "subscription_manager_url": trimmed_url,
                "subscription_id": trimmed_id,
            },
        )
        return {
            "status": "skipped",
            "message_id": None,
            "fault_code": None,
            "fault_subcode": None,
            "fault_reason": None,
        }
    message_id, payload = eventing_builders.build_unsubscribe_request(
        to_url=trimmed_url,
        subscription_identifier=trimmed_id,
        reference_parameters_xml=reference_parameters_xml if reference_parameters_xml else None,
        from_address=from_address,
    )
    log.info(
        "Outbound WS-Eventing unsubscribe sending",
        extra={
            "subscription_manager_url": trimmed_url,
            "subscription_id": trimmed_id,
            "message_id": message_id,
            "timeout_sec": timeout_sec,
        },
    )
    try:
        status, response_text = await _post_soap(
            url=trimmed_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        details = parse_soap_fault(response_text)
        details.update({"status": str(status), "message_id": message_id})
        if status < 200 or status >= 300:
            log.warning(
                "Outbound WS-Eventing unsubscribe returned non-success status",
                extra={
                    "subscription_manager_url": trimmed_url,
                    "status": status,
                    "fault_subcode": details.get("fault_subcode"),
                    "fault_reason": details.get("fault_reason"),
                },
            )
        else:
            log.info(
                "Outbound WS-Eventing unsubscribe completed",
                extra={
                    "subscription_manager_url": trimmed_url,
                    "subscription_id": trimmed_id,
                    "status": status,
                },
            )
        return details
    except asyncio.TimeoutError:
        log.warning(
            "Outbound WS-Eventing unsubscribe timed out",
            extra={
                "subscription_manager_url": trimmed_url,
                "timeout_sec": timeout_sec,
            },
        )
        raise
    except ClientError as exc:
        log.warning(
            "Outbound WS-Eventing unsubscribe transport error",
            extra={"subscription_manager_url": trimmed_url, "error": str(exc)},
        )
        raise


async def renew_subscription(
    *,
    manager_url: str,
    subscription_id: str = "",
    reference_parameters_xml: str | None = None,
    from_address: str | None = None,
    requested_expires: str = "PT1H",
    timeout_sec: float = 5.0,
) -> dict[str, str | None]:
    """Send WS-Eventing Renew to the subscription manager endpoint."""
    trimmed_url = (manager_url or "").strip()
    trimmed_id = (subscription_id or "").strip()
    if not trimmed_url:
        log.info(
            "Skipping WS-Eventing renew (missing subscription manager URL)",
            extra={
                "subscription_manager_url": trimmed_url,
                "subscription_id": trimmed_id,
            },
        )
        return {
            "status": "skipped",
            "message_id": None,
            "expires": None,
            "fault_code": None,
            "fault_subcode": None,
            "fault_reason": None,
        }
    eff_id = _effective_subscription_identifier_for_unsubscribe(
        trimmed_id,
        reference_parameters_xml if reference_parameters_xml else None,
    )
    if not eff_id:
        log.info(
            "Skipping WS-Eventing renew (cannot resolve subscription identifier)",
            extra={
                "subscription_manager_url": trimmed_url,
                "subscription_id": trimmed_id,
            },
        )
        return {
            "status": "skipped",
            "message_id": None,
            "expires": None,
            "fault_code": None,
            "fault_subcode": None,
            "fault_reason": None,
        }
    message_id, payload = eventing_builders.build_renew_request(
        to_url=trimmed_url,
        subscription_identifier=trimmed_id,
        reference_parameters_xml=reference_parameters_xml if reference_parameters_xml else None,
        from_address=from_address,
        requested_expires=requested_expires,
    )
    log.info(
        "Outbound WS-Eventing renew sending",
        extra={
            "subscription_manager_url": trimmed_url,
            "subscription_id": trimmed_id,
            "message_id": message_id,
            "timeout_sec": timeout_sec,
        },
    )
    try:
        status, response_text = await _post_soap(
            url=trimmed_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        parsed = eventing_parsers.parse_renew_response(response_text)
        details = parse_soap_fault(response_text)
        details.update(parsed)
        details.update({"status": str(status), "message_id": message_id})
        if status < 200 or status >= 300:
            log.warning(
                "Outbound WS-Eventing renew returned non-success status",
                extra={
                    "subscription_manager_url": trimmed_url,
                    "status": status,
                    "fault_subcode": details.get("fault_subcode"),
                    "fault_reason": details.get("fault_reason"),
                },
            )
        elif details.get("fault_code"):
            log.warning(
                "Outbound WS-Eventing renew SOAP fault",
                extra={
                    "subscription_manager_url": trimmed_url,
                    "fault_subcode": details.get("fault_subcode"),
                    "fault_reason": details.get("fault_reason"),
                },
            )
        else:
            log.info(
                "Outbound WS-Eventing renew completed",
                extra={
                    "subscription_manager_url": trimmed_url,
                    "subscription_id": trimmed_id,
                    "status": status,
                    "expires": details.get("expires"),
                },
            )
        return details
    except asyncio.TimeoutError:
        log.warning(
            "Outbound WS-Eventing renew timed out",
            extra={
                "subscription_manager_url": trimmed_url,
                "timeout_sec": timeout_sec,
            },
        )
        raise
    except ClientError as exc:
        log.warning(
            "Outbound WS-Eventing renew transport error",
            extra={"subscription_manager_url": trimmed_url, "error": str(exc)},
        )
        raise


def _get_scanner_elements_should_retry_after_invalid_args(
    status: int,
    details: dict[str, str | None],
) -> bool:
    """Return True when a narrower element list may succeed (Epson-style strict QName checks)."""
    if 200 <= status < 300 and not details.get("fault_code"):
        return False
    sub = details.get("fault_subcode") or ""
    return "InvalidArgs" in sub


async def get_scanner_elements_metadata(
    *,
    scanner_xaddr: str,
    timeout_sec: float = 5.0,
    get_to_url: str | None = None,
    from_address: str | None = None,
) -> dict[str, str | None]:
    """Query scanner metadata using WS-Scan GetScannerElements."""
    target_url = get_to_url or resolve_wdp_scan_url(scanner_xaddr)

    async def _fetch(element_names: tuple[str, ...]) -> tuple[int, str, dict[str, str | None], str]:
        message_id, payload = scan_parsers.build_get_scanner_elements_request(
            to_url=target_url,
            element_names=element_names,
            from_address=from_address,
        )
        status, response_text = await _post_soap(
            url=target_url,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        parsed = parse_get_scanner_elements_response(response_text)
        return status, response_text, parsed, message_id

    message_id: str = ""
    log.info(
        "Outbound WS-Scan GetScannerElements sending",
        extra={
            "scanner_xaddr": scanner_xaddr,
            "target_url": target_url,
            "timeout_sec": timeout_sec,
            "requested_element_count": len(SCANNER_METADATA_ELEMENT_NAMES),
        },
    )
    status, _, details, message_id = await _fetch(SCANNER_METADATA_ELEMENT_NAMES)
    details.update({"status": str(status), "message_id": message_id})

    if _get_scanner_elements_should_retry_after_invalid_args(status, details):
        log.info(
            "Outbound WS-Scan GetScannerElements retrying with reduced QName set",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "target_url": target_url,
                "first_fault_subcode": details.get("fault_subcode"),
            },
        )
        status2, _, details2, message_id2 = await _fetch(
            SCANNER_METADATA_ELEMENT_NAMES_NO_DEFAULT_TICKET
        )
        details2.update({"status": str(status2), "message_id": message_id2})
        details = details2
        status = status2
        message_id = message_id2
        if 200 <= status2 < 300 and not details2.get("fault_code"):
            dt_mid: str
            dt_status, _, dt_details, dt_mid = await _fetch(
                (f"{SCANNER_METADATA_ELEMENT_PREFIX}:DefaultScanTicket",)
            )
            dt_details.update({"status": str(dt_status), "message_id": dt_mid})
            if (
                200 <= dt_status < 300
                and not dt_details.get("fault_code")
                and dt_details.get("default_scan_ticket")
            ):
                details["default_scan_ticket"] = dt_details["default_scan_ticket"]

    if status < 200 or status >= 300:
        log.warning(
            "Outbound WS-Scan GetScannerElements returned non-success status",
            extra={
                "scanner_xaddr": scanner_xaddr,
                "target_url": target_url,
                "status": status,
                "fault_subcode": details.get("fault_subcode"),
                "fault_reason": details.get("fault_reason"),
            },
        )
    log.info(
        "Outbound WS-Scan GetScannerElements completed",
        extra={
            "scanner_xaddr": scanner_xaddr,
            "target_url": target_url,
            "status": status,
            "message_id": message_id,
            "has_scanner_description": bool(details.get("scanner_description")),
            "has_default_scan_ticket": bool(details.get("default_scan_ticket")),
            "has_scanner_configuration": bool(details.get("scanner_configuration")),
            "has_scanner_status": bool(details.get("scanner_status")),
            "fault_subcode": details.get("fault_subcode"),
        },
    )
    return details


async def run_scan_available_chain(
    *,
    scanner_xaddr: str,
    scan_available_payload: str | None = None,
    timeout_sec: float = 5.0,
    retrieve_image_timeout_sec: float = 5.0,
    from_address: str | None = None,
    eventing_subscription_identifier: str | None = None,
    subscribe_destination_token: str | None = None,
    subscribe_destination_tokens: dict[str, str] | None = None,
    use_env_subscribe_destination_token_only: bool = False,
    retry_create_without_destination_token_on_invalid_token: bool = True,
    poll_get_job_status_before_retrieve: bool = True,
    get_job_status_max_wait_sec: float = scan_parsers.GET_JOB_STATUS_MAX_WAIT_SEC,
    wait_scanner_idle_after_retrieve: bool = False,
    scanner_idle_wait_sec: float = 60.0,
    scanner_profile: ScannerProfile | None = None,
    output_dir: str | Path | None = None,
    scan_destinations: Sequence[ScanDestination] | None = None,
) -> dict[str, str | None]:
    """Execute ValidateScanTicket, CreateScanJob, optional GetJobStatus polling, then RetrieveImage.

    ``timeout_sec`` applies to control SOAP calls; ``retrieve_image_timeout_sec`` applies only to
    RetrieveImage (chunked MTOM bodies often need far longer than fast request/response pairs).
    """
    target_url = resolve_wdp_scan_url(scanner_xaddr)
    if scanner_profile is not None:
        log.info(
            "Scan chain starting",
            extra={
                "scanner_profile": scanner_profile.key,
                "target_url": target_url,
                "poll_get_job_status_before_retrieve": poll_get_job_status_before_retrieve,
            },
        )
    scanner_metadata: dict[str, str | None] = {
        "probe_http_status": None,
        "probe_message_id": None,
        "probe_fault_code": None,
        "probe_fault_subcode": None,
        "probe_fault_reason": None,
        "scanner_description": None,
        "default_scan_ticket": None,
        "scanner_configuration": None,
        "scanner_status": None,
        "ticket_validation_ok": None,
        "ticket_validation_issues": None,
    }
    try:
        metadata_details = await get_scanner_elements_metadata(
            scanner_xaddr=scanner_xaddr,
            get_to_url=target_url,
            timeout_sec=timeout_sec,
            from_address=from_address,
        )
        scanner_metadata.update(
            {
                "probe_http_status": metadata_details.get("status"),
                "probe_message_id": metadata_details.get("message_id"),
                "probe_fault_code": metadata_details.get("fault_code"),
                "probe_fault_subcode": metadata_details.get("fault_subcode"),
                "probe_fault_reason": metadata_details.get("fault_reason"),
                "scanner_description": metadata_details.get("scanner_description"),
                "default_scan_ticket": metadata_details.get("default_scan_ticket"),
                "scanner_configuration": metadata_details.get("scanner_configuration"),
                "scanner_status": metadata_details.get("scanner_status"),
            }
        )
    except (asyncio.TimeoutError, ClientError) as exc:
        log.warning(
            "Scanner metadata probe failed; continuing scan chain",
            extra={"target_url": target_url, "error": str(exc)},
        )

    event_payload = scan_available_payload or ""
    event_client_context = scan_parsers.extract_client_context(event_payload)
    parsed_caps = parse_scanner_capabilities(scanner_metadata.get("scanner_configuration"))
    dest_seq = scan_destinations if scan_destinations is not None else DEFAULT_DESTINATIONS
    resolved_dest = lookup_destination(event_client_context, dest_seq)

    if resolved_dest is not None and resolved_dest.config is not None:
        scan_ticket_xml = scan_parsers.build_scan_ticket_from_destination_config(
            resolved_dest.config,
            parsed_caps,
        )
        scan_ticket_xml = scan_parsers.apply_scanner_configuration_to_scan_ticket_xml(
            scan_ticket_xml,
            scanner_metadata.get("scanner_configuration"),
        )
    else:
        scan_ticket_xml = scan_parsers.resolve_scan_ticket_xml_for_chain(
            scanner_metadata.get("default_scan_ticket"),
            scanner_metadata.get("scanner_configuration"),
        )

    ticket_validation = scan_parsers.validate_scan_ticket_against_capabilities(
        scan_ticket_xml,
        parsed_caps,
    )
    issues_list = ticket_validation.get("issues") or []
    scanner_metadata["ticket_validation_ok"] = "true" if ticket_validation.get("ok") else "false"
    scanner_metadata["ticket_validation_issues"] = (
        ",".join(str(x) for x in issues_list) if issues_list else None
    )

    validate_message_id, validate_payload = scan_parsers.build_validate_scan_ticket_request(
        to_url=target_url,
        from_address=from_address,
        scan_ticket_xml=scan_ticket_xml,
    )
    validate_status, validate_response_text = await _post_soap(
        url=target_url,
        payload=validate_payload,
        timeout_sec=timeout_sec,
    )
    validate_details = scan_parsers.parse_validate_scan_ticket_response(validate_response_text)
    validate_response_message_id = scan_parsers.extract_soap_envelope_message_id(
        validate_response_text
    )
    scan_identifier = scan_parsers.extract_scan_identifier(event_payload)
    subscription_token = (eventing_subscription_identifier or "").strip() or None
    event_subscription_identifier = scan_parsers.extract_event_subscription_identifier(
        event_payload
    )
    sub_dest = scan_parsers.resolve_subscribe_destination_token_for_chain(
        event_payload=event_payload,
        subscribe_destination_tokens=subscribe_destination_tokens,
        subscribe_destination_token=subscribe_destination_token,
        use_env_subscribe_destination_token_only=use_env_subscribe_destination_token_only,
    )
    # Precedence: SubscribeResponse tokens (per ClientContext when map present), then event hints,
    # then validate response (MessageID heuristic and body token), then persisted WS-Eventing id.
    destination_token = (
        sub_dest
        or scan_parsers.extract_destination_token(event_payload)
        or event_subscription_identifier
        or validate_response_message_id
        or validate_details.get("destination_token")
        or subscription_token
    )
    validate_details["http_status"] = str(validate_status)
    validate_details["message_id"] = validate_message_id
    log.info(
        "ValidateScanTicket completed",
        extra={
            "target_url": target_url,
            "http_status": validate_status,
            "message_id": validate_message_id,
            "status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "subscribe_destination_token": sub_dest,
            "event_client_context": event_client_context,
            "validate_response_message_id": validate_response_message_id,
            "event_subscription_identifier": event_subscription_identifier,
            "subscription_fallback_token": subscription_token,
            "scan_identifier": scan_identifier,
            "fault_subcode": validate_details.get("fault_subcode"),
        },
    )
    valid_ticket = validate_details.get("valid_ticket")
    if (
        validate_status < 200
        or validate_status >= 300
        or validate_details.get("fault_code")
        or (valid_ticket is not None and valid_ticket != "true")
    ):
        return {
            "target_url": target_url,
            **scanner_metadata,
            "validate_http_status": str(validate_status),
            "validate_message_id": validate_message_id,
            "validate_status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "scan_identifier": scan_identifier,
            "fault_code": validate_details.get("fault_code"),
            "fault_subcode": validate_details.get("fault_subcode"),
            "fault_reason": validate_details.get("fault_reason"),
            "create_http_status": None,
            "create_message_id": None,
            "job_id": None,
            "retrieve_http_status": None,
            "retrieve_message_id": None,
            "retrieve_status": None,
            "retrieve_fault_code": None,
            "retrieve_fault_subcode": None,
            "retrieve_fault_reason": None,
            "retrieve_elapsed_sec": None,
            "saved_scan_path": None,
            "saved_scan_bytes": None,
        }

    create_message_id, create_payload = scan_parsers.build_create_scan_job_request(
        to_url=target_url,
        destination_token=destination_token,
        scan_identifier=scan_identifier,
        from_address=from_address,
        scan_ticket_xml=scan_ticket_xml,
    )
    create_status, create_response_text = await _post_soap(
        url=target_url,
        payload=create_payload,
        timeout_sec=timeout_sec,
    )
    create_details = scan_parsers.parse_create_scan_job_response(create_response_text)
    create_used_token = destination_token
    create_used_scan_identifier = scan_identifier
    create_fault_subcode = create_details.get("fault_subcode") or ""
    if (
        retry_create_without_destination_token_on_invalid_token
        and create_status >= 400
        and destination_token
        and create_fault_subcode.endswith(INVALID_DESTINATION_TOKEN_FAULT)
    ):
        # Some firmwares reject DestinationToken (e.g. wrong subscription id shape) but
        # still require ScanIdentifier from ScanAvailableEvent on device-initiated jobs.
        # Retry with DestinationToken omitted only — dropping ScanIdentifier produced requests
        # with only ScanTicket and repeated ClientErrorInvalidDestinationToken in field testing.
        # Gated by config (WSD_CREATE_SCAN_JOB_RETRY_INVALID_DESTINATION_TOKEN).
        log.info(
            "CreateScanJob retrying without DestinationToken after invalid destination token fault",
            extra={
                "target_url": target_url,
                "fault_subcode": create_fault_subcode,
                "original_message_id": create_message_id,
                "preserve_scan_identifier": bool(scan_identifier),
            },
        )
        create_message_id, create_payload = scan_parsers.build_create_scan_job_request(
            to_url=target_url,
            destination_token=None,
            scan_identifier=scan_identifier,
            from_address=from_address,
            scan_ticket_xml=scan_ticket_xml,
        )
        create_status, create_response_text = await _post_soap(
            url=target_url,
            payload=create_payload,
            timeout_sec=timeout_sec,
        )
        create_details = scan_parsers.parse_create_scan_job_response(create_response_text)
        create_used_token = None
        create_used_scan_identifier = scan_identifier

    log.info(
        "CreateScanJob completed",
        extra={
            "target_url": target_url,
            "http_status": create_status,
            "message_id": create_message_id,
            "job_id": create_details.get("job_id"),
            "destination_token": create_used_token,
            "scan_identifier": create_used_scan_identifier,
            "fault_subcode": create_details.get("fault_subcode"),
        },
    )
    create_failed = (
        create_status < 200 or create_status >= 300 or bool(create_details.get("fault_code"))
    )
    resolved_job_id = create_details.get("job_id")
    if create_failed or not resolved_job_id:
        return {
            "target_url": target_url,
            **scanner_metadata,
            "validate_http_status": str(validate_status),
            "validate_message_id": validate_message_id,
            "validate_status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "scan_identifier": scan_identifier,
            "fault_code": create_details.get("fault_code"),
            "fault_subcode": create_details.get("fault_subcode"),
            "fault_reason": create_details.get("fault_reason"),
            "create_http_status": str(create_status),
            "create_message_id": create_message_id,
            "job_id": resolved_job_id,
            "retrieve_http_status": None,
            "retrieve_message_id": None,
            "retrieve_status": None,
            "retrieve_fault_code": None,
            "retrieve_fault_subcode": None,
            "retrieve_fault_reason": None,
            "retrieve_elapsed_sec": None,
            "saved_scan_path": None,
            "saved_scan_bytes": None,
        }

    create_completed_monotonic = time.monotonic()
    create_job_token = create_details.get("job_token")
    if not create_job_token:
        log.info(
            "RetrieveImage skipped: CreateScanJobResponse omitted JobToken (spec requires it for pull)",
            extra={
                "target_url": target_url,
                "job_id": resolved_job_id,
                "create_message_id": create_message_id,
            },
        )
        return {
            "target_url": target_url,
            **scanner_metadata,
            "validate_http_status": str(validate_status),
            "validate_message_id": validate_message_id,
            "validate_status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "scan_identifier": scan_identifier,
            "fault_code": create_details.get("fault_code"),
            "fault_subcode": create_details.get("fault_subcode"),
            "fault_reason": create_details.get("fault_reason"),
            "create_http_status": str(create_status),
            "create_message_id": create_message_id,
            "job_id": resolved_job_id,
            "retrieve_http_status": None,
            "retrieve_message_id": None,
            "retrieve_status": None,
            "retrieve_fault_code": None,
            "retrieve_fault_subcode": None,
            "retrieve_fault_reason": None,
            "retrieve_elapsed_sec": None,
            "saved_scan_path": None,
            "saved_scan_bytes": None,
        }

    poll_result = await poll_get_job_status_until_ready(
        target_url=target_url,
        job_id=resolved_job_id,
        job_token=create_job_token,
        from_address=from_address,
        timeout_sec=timeout_sec,
        max_wait_sec=get_job_status_max_wait_sec,
        enabled=poll_get_job_status_before_retrieve,
    )
    if poll_result.get("terminal_failure"):
        return {
            "target_url": target_url,
            **scanner_metadata,
            "validate_http_status": str(validate_status),
            "validate_message_id": validate_message_id,
            "validate_status": validate_details.get("status"),
            "valid_ticket": validate_details.get("valid_ticket"),
            "destination_token": destination_token,
            "scan_identifier": scan_identifier,
            "fault_code": create_details.get("fault_code"),
            "fault_subcode": create_details.get("fault_subcode"),
            "fault_reason": create_details.get("fault_reason"),
            "create_http_status": str(create_status),
            "create_message_id": create_message_id,
            "job_id": resolved_job_id,
            "retrieve_http_status": None,
            "retrieve_message_id": None,
            "retrieve_status": None,
            "retrieve_fault_code": None,
            "retrieve_fault_subcode": "wscn:JobTerminatedBeforeRetrieve",
            "retrieve_fault_reason": "GetJobStatus reported a terminal job state before image transfer",
            "retrieve_elapsed_sec": None,
            "saved_scan_path": None,
            "saved_scan_bytes": None,
        }

    retrieve_message_id, retrieve_payload = scan_parsers.build_retrieve_image_request(
        to_url=target_url,
        job_id=resolved_job_id,
        job_token=create_job_token,
        from_address=from_address,
    )
    begin_retrieve_idle_wait()
    idle_wait_result: str | None = None
    saved_scan_path_str: str | None = None
    saved_scan_bytes_val: int | None = None
    retrieve_details: dict[str, str | None] = {}
    try:
        retrieve_status, retrieve_body, retrieve_ct = await _post_soap_retrieve_image(
            url=target_url,
            payload=retrieve_payload,
            timeout_sec=retrieve_image_timeout_sec,
        )
        soap_text, image_bytes, image_part_ct = parse_retrieve_image_mtom(
            retrieve_body, retrieve_ct
        )
        retrieve_details = scan_parsers.parse_retrieve_image_response(soap_text)
        fault = retrieve_details.get("fault_code")
        status_val = (retrieve_details.get("status") or "").strip().lower()
        explicit_fail = status_val in ("failure", "failed", "error")
        image_ok = bool(image_bytes)
        retrieve_ok = (
            200 <= retrieve_status < 300
            and not fault
            and not explicit_fail
            and (status_val == "success" or image_ok)
        )
        if retrieve_ok and output_dir is not None and image_bytes:
            try:
                out_subdir: str | None = None
                if resolved_dest is not None and resolved_dest.config is not None:
                    out_subdir = resolved_dest.config.output_subdir
                path = save_scan_file(
                    Path(output_dir),
                    image_bytes,
                    content_type=image_part_ct,
                    subdir=out_subdir,
                )
                saved_scan_path_str = str(path)
                saved_scan_bytes_val = len(image_bytes)
                if resolved_dest is not None:
                    for hook in resolved_dest.post_processing_hooks:
                        hook(path)
            except OSError:
                log.exception(
                    "Failed to persist RetrieveImage payload",
                    extra={"target_url": target_url, "job_id": resolved_job_id},
                )
        elif retrieve_ok and image_bytes and output_dir is None:
            log.info(
                "RetrieveImage returned image bytes but output_dir omitted; skipping save",
                extra={"bytes": len(image_bytes), "job_id": resolved_job_id},
            )
        if retrieve_ok and wait_scanner_idle_after_retrieve and scanner_idle_wait_sec > 0:
            got_idle = await await_scanner_idle_after_retrieve(scanner_idle_wait_sec)
            idle_wait_result = "success" if got_idle else "timeout"
            if got_idle:
                log.info(
                    "Scanner Idle after RetrieveImage (ScannerStatusSummaryEvent)",
                    extra={
                        "target_url": target_url,
                        "job_id": resolved_job_id,
                        "scanner_idle_wait_sec": scanner_idle_wait_sec,
                    },
                )
        elif retrieve_ok:
            idle_wait_result = "skipped"
        else:
            idle_wait_result = "not_applicable"
    finally:
        end_retrieve_idle_wait()
    retrieve_elapsed_sec = time.monotonic() - create_completed_monotonic
    retrieve_fault_subcode = retrieve_details.get("fault_subcode") or ""
    log.info(
        "RetrieveImage completed",
        extra={
            "target_url": target_url,
            "http_status": retrieve_status,
            "message_id": retrieve_message_id,
            "job_id": resolved_job_id,
            "job_token": create_job_token,
            "fault_subcode": retrieve_details.get("fault_subcode"),
            "retrieve_elapsed_sec": round(retrieve_elapsed_sec, 6),
            "within_retrieve_window_60s": retrieve_elapsed_sec <= 60.0,
            "scanner_idle_wait_result": idle_wait_result,
            "saved_scan_path": saved_scan_path_str,
            "saved_scan_bytes": saved_scan_bytes_val,
        },
    )
    if retrieve_elapsed_sec > 60.0:
        log.warning(
            "RetrieveImage exceeded 60s guideline after CreateScanJob",
            extra={
                "target_url": target_url,
                "job_id": resolved_job_id,
                "job_token": create_job_token,
                "retrieve_elapsed_sec": round(retrieve_elapsed_sec, 6),
            },
        )
    if "JobTimedOut" in retrieve_fault_subcode:
        log.warning(
            "RetrieveImage fault JobTimedOut",
            extra={
                "target_url": target_url,
                "job_id": resolved_job_id,
                "job_token": create_job_token,
                "fault_subcode": retrieve_fault_subcode,
            },
        )
    if (
        "NoImagesAvailable" in retrieve_fault_subcode
        or "ClientErrorNoImagesAvailable" in retrieve_fault_subcode
    ):
        log.warning(
            "RetrieveImage fault no images available",
            extra={
                "target_url": target_url,
                "job_id": resolved_job_id,
                "job_token": create_job_token,
                "fault_subcode": retrieve_fault_subcode,
            },
        )
    return {
        "target_url": target_url,
        **scanner_metadata,
        "validate_http_status": str(validate_status),
        "validate_message_id": validate_message_id,
        "validate_status": validate_details.get("status"),
        "valid_ticket": validate_details.get("valid_ticket"),
        "destination_token": destination_token,
        "scan_identifier": scan_identifier,
        "fault_code": create_details.get("fault_code"),
        "fault_subcode": create_details.get("fault_subcode"),
        "fault_reason": create_details.get("fault_reason"),
        "create_http_status": str(create_status),
        "create_message_id": create_message_id,
        "job_id": resolved_job_id,
        "retrieve_http_status": str(retrieve_status),
        "retrieve_message_id": retrieve_message_id,
        "retrieve_status": retrieve_details.get("status"),
        "retrieve_fault_code": retrieve_details.get("fault_code"),
        "retrieve_fault_subcode": retrieve_details.get("fault_subcode"),
        "retrieve_fault_reason": retrieve_details.get("fault_reason"),
        "retrieve_elapsed_sec": f"{retrieve_elapsed_sec:.6f}",
        "scanner_idle_wait_result": idle_wait_result,
        "saved_scan_path": saved_scan_path_str,
        "saved_scan_bytes": str(saved_scan_bytes_val) if saved_scan_bytes_val is not None else None,
    }

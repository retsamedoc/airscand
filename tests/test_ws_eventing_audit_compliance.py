"""Contract tests aligned with ``docs/ws-eventing_audit.md`` §17 checklist.

Each test name maps to audit themes (fault mapping, lifecycle, outbound renew).
*Why:* the audit calls out sparse coverage; these tests lock regressions for both
inbound subscription-manager and outbound subscriber roles.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

import main
from app.inbound_eventing_registry import reset_inbound_subscription_registry
from app.soap.fault import parse_soap_fault
from app.ws_scan import ACTION_GET_STATUS, ACTION_RENEW, ACTION_UNSUBSCRIBE, handle_wsd
from tests.test_ws_scan import _management_envelope, _request, _subscribe_push_envelope

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def _reset_inbound_eventing_registry() -> None:
    """Isolate inbound subscription state (same pattern as ``test_ws_scan``)."""
    reset_inbound_subscription_registry()
    yield
    reset_inbound_subscription_registry()


@pytest.mark.asyncio
async def test_audit_ws_eventing_17_inbound_subscribe_empty_notifyto_invalid_message(
    monkeypatch: MonkeyPatch,
) -> None:
    """``docs/ws-eventing_audit.md`` §5 / §4 — Push ``NotifyTo`` address required."""
    monkeypatch.setattr(
        "app.ws_scan._max_inbound_eventing_grant_seconds", lambda _c: 3600, raising=True
    )
    payload = _subscribe_push_envelope(notify_to="")
    response = await handle_wsd(_request(payload))
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:InvalidMessage"


@pytest.mark.asyncio
async def test_audit_ws_eventing_17_inbound_getstatus_unknown_id_unable_to_renew() -> None:
    """``docs/ws-eventing_audit.md`` §1 / §12 — unknown id on ``GetStatus`` faults consistently."""
    response = await handle_wsd(
        _request(_management_envelope(ACTION_GET_STATUS, "urn:uuid:gs1", "urn:uuid:no-such-sub"))
    )
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:UnableToRenew"


@pytest.mark.asyncio
async def test_audit_ws_eventing_17_inbound_unsubscribe_unknown_id_unable_to_destroy() -> None:
    """``docs/ws-eventing_audit.md`` §1 / §4 — unknown id on ``Unsubscribe`` → ``UnableToDestroy``."""
    response = await handle_wsd(
        _request(_management_envelope(ACTION_UNSUBSCRIBE, "urn:uuid:us1", "urn:uuid:no-such-sub"))
    )
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:UnableToDestroySubscription"


@pytest.mark.asyncio
async def test_audit_ws_eventing_17_inbound_renew_wsa_to_mismatch_invalid_message() -> None:
    """``docs/ws-eventing_audit.md`` §1 — ``wsa:To`` must match this manager endpoint."""
    sub_resp = await handle_wsd(_request(_subscribe_push_envelope("urn:uuid:sub-m")))
    assert "SubscribeResponse" in sub_resp.text
    start = sub_resp.text.index("<wsman:Identifier>")
    end = sub_resp.text.index("</wsman:Identifier>", start)
    sub_id = sub_resp.text[start + len("<wsman:Identifier>") : end].strip()

    bad_to = "http://wrong-host/wsd"
    response = await handle_wsd(
        _request(
            _management_envelope(
                ACTION_RENEW,
                "urn:uuid:renew-bad-to",
                sub_id,
                manager_to=bad_to,
            )
        )
    )
    fault = parse_soap_fault(response.text)
    assert fault.get("fault_subcode") == "wse:InvalidMessage"


@pytest.mark.asyncio
async def test_audit_ws_eventing_17_outbound_renew_soap_fault_triggers_unsubscribe_best_effort(
    monkeypatch: MonkeyPatch,
) -> None:
    """``docs/ws-eventing_audit.md`` §2 / §17 — failed ``Renew`` runs best-effort ``Unsubscribe``."""
    cfg = SimpleNamespace(
        scanner_eventing_subscribe_expires="PT3600S",
        scanner_eventing_subscription_id="urn:uuid:primary-sub",
        scanner_eventing_subscribe_manager_url="http://192.168.1.60/WDP/SCAN/mgr",
        scanner_eventing_subscribe_manager_reference_parameters_xml="",
        scanner_eventing_subscription_id_status="",
        scanner_eventing_subscribe_manager_url_status="",
        scanner_eventing_subscribe_manager_reference_parameters_xml_status="",
        scanner_eventing_subscribe_expires_status="",
        eventing_renew_after_fraction=0.5,
        eventing_renew_fallback_duration_sec=3600.0,
    )
    monkeypatch.setattr(main, "_renew_delay_seconds", lambda _expires, _config: 0.0)

    unsub_calls: list[dict[str, str | None]] = []

    async def fake_renew(
        *,
        manager_url: str,
        subscription_id: str = "",
        reference_parameters_xml: str | None = None,
        from_address: str | None = None,
        requested_expires: str = "PT1H",
        timeout_sec: float = 5.0,
    ) -> dict[str, str | None]:
        assert manager_url == cfg.scanner_eventing_subscribe_manager_url
        assert subscription_id == cfg.scanner_eventing_subscription_id
        return {
            "status": "200",
            "message_id": "urn:uuid:renew-fail",
            "expires": None,
            "fault_code": "soap:Sender",
            "fault_subcode": "wse:UnableToRenew",
            "fault_reason": "Device rejected renew",
        }

    async def fake_unsub(
        *,
        manager_url: str,
        subscription_id: str,
        reference_parameters_xml: str | None = None,
        from_address: str | None = None,
        timeout_sec: float = 5.0,
    ) -> dict[str, str | None]:
        unsub_calls.append(
            {
                "manager_url": manager_url,
                "subscription_id": subscription_id,
                "from_address": from_address,
            }
        )
        return {"status": "200"}

    monkeypatch.setattr(main, "renew_subscription", fake_renew)
    monkeypatch.setattr(main, "unsubscribe_from_scanner", fake_unsub)

    await main._eventing_maintenance_loop(cfg, client_from_address="urn:uuid:client-1")

    assert len(unsub_calls) == 1
    assert unsub_calls[0]["manager_url"] == cfg.scanner_eventing_subscribe_manager_url
    assert unsub_calls[0]["subscription_id"] == cfg.scanner_eventing_subscription_id
    assert unsub_calls[0]["from_address"] == "urn:uuid:client-1"

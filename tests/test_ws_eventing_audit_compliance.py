"""Contract tests aligned with ``docs/ws-eventing_audit.md`` §17 checklist.

Each test name maps to audit themes (fault mapping, lifecycle, outbound renew).
*Why:* the audit calls out sparse coverage; these tests lock regressions for both
inbound subscription-manager and outbound subscriber roles.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

import main
from app.inbound_eventing_registry import reset_inbound_subscription_registry
from app.soap.fault import parse_soap_fault
from app.ws_eventing_client import SCANNER_STATUS_SUMMARY_EVENT_ACTION
from app.ws_scan import ACTION_GET_STATUS, ACTION_RENEW, ACTION_UNSUBSCRIBE, handle_wsd
from main import _eventing_registration_loop
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


@pytest.mark.asyncio
async def test_audit_ws_eventing_17_outbound_dual_renew_status_failure_unsubscribes_both_ordered(
    monkeypatch: MonkeyPatch,
) -> None:
    """``docs/ws-eventing_audit.md`` §2 / §17 — failed status ``Renew`` unsubscribes both subscriptions.

    ``_unsubscribe_eventing_best_effort`` tears down ``ScannerStatusSummary`` before the primary
    subscription so the device does not keep a dangling status lease.
    """
    cfg = SimpleNamespace(
        scanner_eventing_subscribe_expires="PT7200S",
        scanner_eventing_subscription_id="urn:uuid:primary-sub",
        scanner_eventing_subscribe_manager_url="http://192.168.1.60/WDP/SCAN/mgr-primary",
        scanner_eventing_subscribe_manager_reference_parameters_xml="",
        scanner_eventing_subscription_id_status="urn:uuid:status-sub",
        scanner_eventing_subscribe_manager_url_status="http://192.168.1.60/WDP/SCAN/mgr-status",
        scanner_eventing_subscribe_manager_reference_parameters_xml_status="",
        scanner_eventing_subscribe_expires_status="PT4S",
        eventing_renew_after_fraction=0.5,
        eventing_renew_fallback_duration_sec=3600.0,
    )

    def staggered_renew_delay(expires_raw: str, _config: object) -> float:
        """Wake status renewal first without relying on real clock sleeps."""
        if (expires_raw or "").strip() == "PT7200S":
            return 10_000.0
        return 0.0

    monkeypatch.setattr(main, "_renew_delay_seconds", staggered_renew_delay)

    unsub_calls: list[dict[str, str]] = []

    async def fake_renew(
        *,
        manager_url: str,
        subscription_id: str = "",
        reference_parameters_xml: str | None = None,
        from_address: str | None = None,
        requested_expires: str = "PT1H",
        timeout_sec: float = 5.0,
    ) -> dict[str, str | None]:
        if subscription_id == cfg.scanner_eventing_subscription_id_status:
            return {
                "status": "200",
                "message_id": "urn:uuid:renew-status-fail",
                "expires": None,
                "fault_code": "soap:Sender",
                "fault_subcode": "wse:UnableToRenew",
                "fault_reason": "Device rejected status renew",
            }
        raise AssertionError("primary Renew should not run before status Renew in this scenario")

    async def fake_unsub(
        *,
        manager_url: str,
        subscription_id: str,
        reference_parameters_xml: str | None = None,
        from_address: str | None = None,
        timeout_sec: float = 5.0,
    ) -> dict[str, str | None]:
        unsub_calls.append({"manager_url": manager_url, "subscription_id": subscription_id})
        return {"status": "200"}

    monkeypatch.setattr(main, "renew_subscription", fake_renew)
    monkeypatch.setattr(main, "unsubscribe_from_scanner", fake_unsub)

    await main._eventing_maintenance_loop(cfg, client_from_address="urn:uuid:client-1")

    assert len(unsub_calls) == 2
    assert unsub_calls[0]["subscription_id"] == cfg.scanner_eventing_subscription_id_status
    assert unsub_calls[0]["manager_url"] == cfg.scanner_eventing_subscribe_manager_url_status
    assert unsub_calls[1]["subscription_id"] == cfg.scanner_eventing_subscription_id
    assert unsub_calls[1]["manager_url"] == cfg.scanner_eventing_subscribe_manager_url


@pytest.mark.asyncio
async def test_audit_ws_eventing_17_registration_resubscribes_after_maintenance_exit(
    monkeypatch: MonkeyPatch,
) -> None:
    """``docs/ws-eventing_audit.md`` §17 — outer registration loop performs backoff then a full resubscribe.

    When ``_eventing_maintenance_loop`` returns, ``_eventing_registration_loop`` sleeps using the
    post-success backoff (reset to 2s) and runs ``register_with_scanner`` again for both filters.
    """
    cfg = SimpleNamespace(
        advertise_addr="192.168.1.50",
        port=5357,
        endpoint_path="/wsd",
        uuid="11111111-2222-3333-4444-555555555555",
        eventing_notify_to_url="",
        eventing_preflight_get=True,
        scanner_subscribe_to_url="",
        scanner_eventing_subscribe_manager_url="",
        scanner_eventing_subscription_id="",
        scanner_eventing_subscription_id_status="",
        scanner_subscribe_destination_tokens={},
        use_env_subscribe_destination_token_only=False,
        eventing_renew_after_fraction=0.9,
        eventing_renew_min_sleep_sec=5.0,
        eventing_renew_fallback_duration_sec=3600.0,
        validate_outbound_soap_response=False,
    )
    sleep_durations: list[float] = []
    maintenance_exits = {"n": 0}
    stop_registration = asyncio.Event()
    real_asyncio_sleep = asyncio.sleep

    async def instant_sleep(seconds: float) -> None:
        sleep_durations.append(float(seconds))
        await real_asyncio_sleep(0)

    async def fake_discover(_config: object) -> list[str]:
        return ["http://192.168.1.60:80/WSD/DEVICE"]

    async def fake_preflight(
        *,
        scanner_xaddr: str,
        timeout_sec: float = 5.0,
        get_to_url: str | None = None,
        from_address: str | None = None,
    ) -> dict[str, str | None]:
        return {"suggested_subscribe_to_url": None, "message_id": "urn:uuid:get-1"}

    register_phases: list[str] = []

    async def fake_register(
        *,
        scanner_xaddr: str,
        notify_to: str,
        timeout_sec: float = 5.0,
        subscribe_to_url: str | None = None,
        from_address: str | None = None,
        subscription_identifier: str | None = None,
        filter_action: str | None = None,
        scan_destinations: tuple[tuple[str, str], ...] | None = None,
        **_kwargs: object,
    ) -> dict[str, str]:
        assert scanner_xaddr == "http://192.168.1.60:80/WSD/DEVICE"
        assert subscribe_to_url == "http://192.168.1.60:80/WDP/SCAN"
        assert notify_to == "http://192.168.1.50:5357/wsd"
        assert from_address == "urn:uuid:11111111-2222-3333-4444-555555555555"
        if filter_action == SCANNER_STATUS_SUMMARY_EVENT_ACTION:
            register_phases.append("status")
            return {
                "status": "200",
                "identifier": f"sub-status-{register_phases.count('status')}",
                "expires": "PT1H",
                "subscribe_destination_token": "dest",
                "subscribe_destination_tokens": {"Scan": "dest"},
                "subscription_manager_url": (
                    f"http://192.168.1.60:80/WDP/SCAN/submgr-status-{register_phases.count('status')}"
                ),
            }
        register_phases.append("primary")
        return {
            "status": "200",
            "identifier": f"sub-primary-{register_phases.count('primary')}",
            "expires": "PT1H",
            "subscribe_destination_token": "dest",
            "subscribe_destination_tokens": {"Scan": "dest"},
            "subscription_manager_url": (
                f"http://192.168.1.60:80/WDP/SCAN/submgr-{register_phases.count('primary')}"
            ),
        }

    async def fake_maintenance(_config: object, *, client_from_address: str) -> None:
        maintenance_exits["n"] += 1
        if maintenance_exits["n"] >= 2:
            stop_registration.set()

    monkeypatch.setattr(main.asyncio, "sleep", instant_sleep)
    monkeypatch.setattr(main, "discover_scanner_xaddrs", fake_discover)
    monkeypatch.setattr(main, "preflight_get_scanner_capabilities", fake_preflight)
    monkeypatch.setattr(main, "register_with_scanner", fake_register)
    orig_maintenance = main._eventing_maintenance_loop
    main._eventing_maintenance_loop = fake_maintenance  # type: ignore[method-assign]
    try:
        task = asyncio.create_task(_eventing_registration_loop(cfg))
        await asyncio.wait_for(stop_registration.wait(), timeout=5.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        main._eventing_maintenance_loop = orig_maintenance  # type: ignore[method-assign]

    assert maintenance_exits["n"] == 2
    assert register_phases == ["primary", "status", "primary", "status"]
    assert sleep_durations[:2] == [2.0, 2.0]
    assert cfg.scanner_eventing_subscription_id == "sub-primary-2"
    assert cfg.scanner_eventing_subscription_id_status == "sub-status-2"

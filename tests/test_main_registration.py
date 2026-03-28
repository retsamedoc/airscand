"""Registration loop behavior tests."""

from __future__ import annotations

import runpy
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from main import _eventing_registration_loop, _resolve_subscribe_to_url

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


@pytest.mark.asyncio
async def test_eventing_registration_loop_retries_then_succeeds(monkeypatch: MonkeyPatch) -> None:
    """Registration retries discovery and succeeds after endpoint appears."""
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
    )
    attempts = {"discover": 0, "register": 0, "preflight": 0}

    async def fake_discover(_config: object) -> str | None:
        attempts["discover"] += 1
        if attempts["discover"] < 2:
            return None
        return "http://192.168.1.60:80/WSD/DEVICE"

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
    ) -> dict[str, str]:
        attempts["register"] += 1
        assert scanner_xaddr == "http://192.168.1.60:80/WSD/DEVICE"
        assert subscribe_to_url == "http://192.168.1.60:80/WDP/SCAN"
        assert notify_to == "http://192.168.1.50:5357/wsd"
        assert from_address == "urn:uuid:11111111-2222-3333-4444-555555555555"
        if attempts["register"] == 1:
            return {
                "identifier": "sub-1",
                "expires": "PT1H",
                "subscribe_destination_token": "dest-from-subscribe",
                "subscribe_destination_tokens": {"Scan": "dest-from-subscribe"},
            }
        return {
            "identifier": "sub-status-1",
            "expires": "PT1H",
            "subscribe_destination_token": "dest-from-subscribe",
            "subscribe_destination_tokens": {"Scan": "dest-from-subscribe"},
        }

    async def fake_preflight_wdp(
        *,
        scanner_xaddr: str,
        timeout_sec: float = 5.0,
        get_to_url: str | None = None,
        from_address: str | None = None,
    ) -> dict[str, str | None]:
        attempts["preflight"] += 1
        assert scanner_xaddr == "http://192.168.1.60:80/WSD/DEVICE"
        assert get_to_url == "http://192.168.1.60:80/WDP/SCAN"
        assert from_address == "urn:uuid:11111111-2222-3333-4444-555555555555"
        return {"suggested_subscribe_to_url": None, "message_id": "urn:uuid:get-1"}

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("main.discover_scanner_xaddr", fake_discover)
    monkeypatch.setattr("main.preflight_get_scanner_capabilities", fake_preflight_wdp)
    monkeypatch.setattr("main.register_with_scanner", fake_register)
    monkeypatch.setattr("main.asyncio.sleep", fake_sleep)

    await _eventing_registration_loop(cfg)
    assert attempts["discover"] == 2
    assert attempts["preflight"] == 1
    assert attempts["register"] == 2
    assert cfg.scanner_eventing_subscription_id == "sub-1"
    assert cfg.scanner_eventing_subscription_id_status == "sub-status-1"
    assert cfg.scanner_eventing_subscribe_manager_url == "http://192.168.1.60:80/WDP/SCAN"
    assert cfg.scanner_subscribe_destination_token == "dest-from-subscribe"
    assert cfg.scanner_subscribe_destination_tokens == {"Scan": "dest-from-subscribe"}
    assert cfg.use_env_subscribe_destination_token_only is False


def test_resolve_subscribe_to_url_prefers_explicit_override() -> None:
    """Explicit subscribe URL override is preferred."""
    cfg = SimpleNamespace(
        scanner_subscribe_to_url="http://192.168.1.60:80/custom/subscribe",
    )
    assert (
        _resolve_subscribe_to_url(cfg, "http://192.168.1.60:80/WSD/DEVICE")
        == "http://192.168.1.60:80/custom/subscribe"
    )


def test_resolve_subscribe_to_url_defaults_to_wdp_scan() -> None:
    """Default subscribe URL resolves to scanner /WDP/SCAN path."""
    cfg = SimpleNamespace(
        scanner_subscribe_to_url="",
    )
    assert _resolve_subscribe_to_url(cfg, "http://192.168.1.60:80/WSD/DEVICE") == (
        "http://192.168.1.60:80/WDP/SCAN"
    )


@pytest.mark.asyncio
async def test_eventing_registration_loop_uses_preflight_suggested_destination(
    monkeypatch: MonkeyPatch,
) -> None:
    """Preflight suggested destination is used for Subscribe."""
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
        scanner_subscribe_destination_token="",
        scanner_subscribe_destination_tokens={},
        use_env_subscribe_destination_token_only=False,
    )
    calls = []

    async def fake_discover(_config: object) -> str:
        return "http://192.168.1.60:80/WSD/DEVICE"

    async def fake_preflight(
        *,
        scanner_xaddr: str,
        timeout_sec: float = 5.0,
        get_to_url: str | None = None,
        from_address: str | None = None,
    ) -> dict[str, str]:
        return {
            "suggested_subscribe_to_url": "http://192.168.1.60:80/WDP/SCAN",
            "message_id": "urn:uuid:get-1",
        }

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
    ) -> dict[str, str | None]:
        calls.append(subscribe_to_url)
        n = len(calls)
        return {
            "status": "200",
            "fault_subcode": None,
            "identifier": f"sub-{n}",
            "expires": "PT1H",
            "subscribe_destination_token": None,
        }

    monkeypatch.setattr("main.discover_scanner_xaddr", fake_discover)
    monkeypatch.setattr("main.preflight_get_scanner_capabilities", fake_preflight)
    monkeypatch.setattr("main.register_with_scanner", fake_register)

    await _eventing_registration_loop(cfg)
    assert calls == [
        "http://192.168.1.60:80/WDP/SCAN",
        "http://192.168.1.60:80/WDP/SCAN",
    ]
    assert cfg.scanner_eventing_subscription_id == "sub-1"
    assert cfg.scanner_eventing_subscription_id_status == "sub-2"
    assert cfg.scanner_eventing_subscribe_manager_url == "http://192.168.1.60:80/WDP/SCAN"
    assert cfg.scanner_subscribe_destination_token == ""
    assert cfg.scanner_subscribe_destination_tokens == {}
    assert cfg.use_env_subscribe_destination_token_only is False


def test_main_entrypoint_handles_keyboard_interrupt(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    """Module entrypoint swallows Ctrl-C and emits a clean shutdown log."""

    def fake_asyncio_run(coroutine_obj: object) -> None:
        coroutine_close = getattr(coroutine_obj, "close", None)
        if callable(coroutine_close):
            coroutine_close()
        raise KeyboardInterrupt

    caplog.set_level("INFO", logger="__main__")
    monkeypatch.setattr("asyncio.run", fake_asyncio_run)

    runpy.run_module("main", run_name="__main__")

    assert any("Shutdown requested; exiting" in message for message in caplog.messages)

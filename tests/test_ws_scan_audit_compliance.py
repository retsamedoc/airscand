"""Contract tests aligned with ``docs/ws-scan_audit.md`` checklist themes.

Each ``test_audit_ws_scan_*`` name maps to an audit section (resolved behaviors and
documented residual gaps). *Why:* WS-Scan interop is spread across orchestration and
parsers; audit-named tests give CI a single module to run when hardening pull/push paths.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from app.mtom import MtomPayloadIntegrityReport
from app.soap.namespaces import NS_SOAP
from app.soap.transport import HttpBodyIntegrityReport, SoapHttpClient
from app.ws_eventing_client import (
    ACTION_CREATE_SCAN_JOB,
    ACTION_GET_SCANNER_ELEMENTS,
    ACTION_RETRIEVE_IMAGE,
    ACTION_VALIDATE_SCAN_TICKET,
    parse_create_scan_job_response,
    parse_get_response,
    parse_retrieve_image_response,
    run_scan_available_chain,
)
from app.ws_scan import (
    ACTION_SCAN_AVAILABLE_EVENT,
    ACTION_SCAN_AVAILABLE_EVENT_RESPONSE,
    build_scan_available_event_ack_response,
    handle_wsd,
)
from tests.test_ws_eventing_client import (
    _fake_retrieve_image_from_xml,
    _retrieve_image_http_ok,
)
from tests.test_ws_scan import (
    _minimal_action_envelope,
    _request,
    _request_missing_config,
)

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


def _minimal_gse_xml() -> str:
    """GetScannerElements response with a default scan ticket for chain tests."""
    return """<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:GetScannerElementsResponse>
    <sca:DefaultScanTicket>
      <sca:ScanTicket>
        <sca:JobDescription><sca:JobName>Audit</sca:JobName></sca:JobDescription>
      </sca:ScanTicket>
    </sca:DefaultScanTicket>
  </sca:GetScannerElementsResponse></soap:Body>
</soap:Envelope>"""


def _validate_ok_xml() -> str:
    return f"""<soap:Envelope xmlns:soap="{NS_SOAP}"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>"""


def _create_ok_xml(*, job_id: str = "job-audit", job_token: str = "tok-audit") -> str:
    return f"""<soap:Envelope xmlns:soap="{NS_SOAP}"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>{job_id}</sca:JobId><sca:JobToken>{job_token}</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>"""


def _retrieve_soap_fault_xml(*, subcode: str, reason: str) -> str:
    return f"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="{NS_SOAP}">
  <soap:Body>
    <soap:Fault>
      <soap:Code>
        <soap:Value>soap:Sender</soap:Value>
        <soap:Subcode><soap:Value>{subcode}</soap:Value></soap:Subcode>
      </soap:Code>
      <soap:Reason><soap:Text xml:lang="en">{reason}</soap:Text></soap:Reason>
    </soap:Fault>
  </soap:Body>
</soap:Envelope>"""


@pytest.mark.parametrize(
    ("subcode", "log_fragment"),
    [
        ("wscn:JobTimedOut", "RetrieveImage fault JobTimedOut"),
        ("wscn:NoImagesAvailable", "RetrieveImage fault no images available"),
        ("wscn:ClientErrorNoImagesAvailable", "RetrieveImage fault no images available"),
    ],
)
@pytest.mark.asyncio
async def test_audit_ws_scan_06_retrieve_fault_subcode_and_warning_logs(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
    subcode: str,
    log_fragment: str,
) -> None:
    """``docs/ws-scan_audit.md`` §6 — retrieve timing/fault warnings surface in logs and result."""
    caplog.set_level(logging.WARNING)

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, _minimal_gse_xml()
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, _validate_ok_xml()
        if ACTION_CREATE_SCAN_JOB in payload:
            return 200, _create_ok_xml()
        raise AssertionError("unexpected SOAP leg")

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    monkeypatch.setattr(
        "app.ws_eventing_client._post_soap_retrieve_image",
        _fake_retrieve_image_from_xml(
            _retrieve_soap_fault_xml(subcode=subcode, reason="peer fault"),
            status=500,
        ),
    )
    monkeypatch.setattr(
        "app.ws_eventing_client.parse_retrieve_image_mtom",
        lambda body, ct: (body.decode("utf-8"), None, None, MtomPayloadIntegrityReport(ok=True)),
    )

    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
        wait_scanner_idle_after_retrieve=False,
    )
    assert subcode in (result.get("retrieve_fault_subcode") or "")
    assert log_fragment in caplog.text


@pytest.mark.asyncio
async def test_audit_ws_scan_06_retrieve_elapsed_over_60s_logs_guideline_warning(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    """``docs/ws-scan_audit.md`` §6 — create→retrieve elapsed > 60s emits guideline warning."""
    caplog.set_level(logging.WARNING)
    mono = {"t": 1000.0}

    def fake_monotonic() -> float:
        return mono["t"]

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, _minimal_gse_xml()
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, _validate_ok_xml()
        if ACTION_CREATE_SCAN_JOB in payload:
            mono["t"] = 1000.0
            return 200, _create_ok_xml()
        raise AssertionError("unexpected SOAP leg")

    async def slow_retrieve(
        *, url: str, payload: str, timeout_sec: float
    ) -> tuple[int, bytes, str | None, HttpBodyIntegrityReport]:
        assert ACTION_RETRIEVE_IMAGE in payload
        mono["t"] = 1062.0
        raw = _retrieve_soap_fault_xml(subcode="wscn:JobTimedOut", reason="late").encode()
        return 500, raw, "application/soap+xml; charset=utf-8", _retrieve_image_http_ok(raw)

    monkeypatch.setattr("app.ws_eventing_client.time.monotonic", fake_monotonic)
    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    monkeypatch.setattr("app.ws_eventing_client._post_soap_retrieve_image", slow_retrieve)
    monkeypatch.setattr(
        "app.ws_eventing_client.parse_retrieve_image_mtom",
        lambda body, ct: (body.decode("utf-8"), None, None, MtomPayloadIntegrityReport(ok=True)),
    )

    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
        wait_scanner_idle_after_retrieve=False,
    )
    assert float(result.get("retrieve_elapsed_sec") or "0") > 60.0
    assert "RetrieveImage exceeded 60s guideline after CreateScanJob" in caplog.text


@pytest.mark.asyncio
async def test_audit_ws_scan_14_soap_http_client_content_type_only_baseline() -> None:
    """``docs/ws-scan_audit.md`` §14 — outbound SOAP uses ``Content-Type`` only (no ``SOAPAction``)."""

    class _CapturingSession:
        last_headers: dict[str, str] = {}

        def post(self, *args: object, **kwargs: object) -> object:
            _CapturingSession.last_headers = dict(kwargs.get("headers") or {})
            return _FakePostContext()

    class _FakePostContext:
        status = 200

        async def text(self) -> str:
            return _minimal_gse_xml()

        async def __aenter__(self) -> _FakePostContext:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

    client = SoapHttpClient(session=_CapturingSession())  # type: ignore[arg-type]
    await client.post_text(url="http://127.0.0.1:9/soap", payload="<x/>", timeout_sec=5.0)
    headers = _CapturingSession.last_headers
    assert headers.get("Content-Type") == "application/soap+xml; charset=utf-8"
    assert "SOAPAction" not in headers
    assert "action=" not in (headers.get("Content-Type") or "")


def test_audit_ws_scan_13_parse_create_scan_job_response_wscn_prefix() -> None:
    """``docs/ws-scan_audit.md`` §13 — ``wscn:`` prefix on response elements still parses."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <wscn:CreateScanJobResponse>
      <wscn:JobId>job-wscn</wscn:JobId>
      <wscn:JobToken>tok-wscn</wscn:JobToken>
    </wscn:CreateScanJobResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_create_scan_job_response(xml)
    assert parsed["job_id"] == "job-wscn"
    assert parsed["job_token"] == "tok-wscn"


def test_audit_ws_scan_13_parse_retrieve_image_response_first_status_in_body() -> None:
    """``docs/ws-scan_audit.md`` §13 — ``Status`` extraction uses first match in envelope (documented)."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body>
    <sca:RetrieveImageResponse>
      <sca:Nested><sca:Status>Decoy</sca:Status></sca:Nested>
      <sca:Status>Success</sca:Status>
    </sca:RetrieveImageResponse>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_retrieve_image_response(xml)
    assert parsed["status"] == "Decoy"


def test_audit_ws_scan_07_scan_available_event_ack_soap_shape() -> None:
    """``docs/ws-scan_audit.md`` §7 — ScanAvailableEvent ack is SOAP 1.2 with RelatesTo and response Action."""
    xml = build_scan_available_event_ack_response("urn:uuid:notify-audit")
    assert "<soap:Envelope" in xml
    assert f"<wsa:Action>{ACTION_SCAN_AVAILABLE_EVENT_RESPONSE}</wsa:Action>" in xml
    assert "<wsa:RelatesTo>urn:uuid:notify-audit</wsa:RelatesTo>" in xml


@pytest.mark.asyncio
async def test_audit_ws_scan_07_handle_wsd_scan_available_triggers_chain_with_soap_ack(
    monkeypatch: MonkeyPatch,
) -> None:
    """``docs/ws-scan_audit.md`` §7 — inbound ScanAvailableEvent returns SOAP ack and schedules chain."""
    calls: list[str] = []

    async def fake_chain(
        *,
        scanner_xaddr: str,
        scan_available_payload: str | None = None,
        **kwargs: object,
    ) -> dict[str, str | None]:
        calls.append(scanner_xaddr)
        return {"target_url": "http://192.168.1.60:80/WDP/SCAN", "job_id": "job-ack"}

    monkeypatch.setattr("app.ws_scan.run_scan_available_chain", fake_chain)
    response = await handle_wsd(_request(_minimal_action_envelope(ACTION_SCAN_AVAILABLE_EVENT)))
    await asyncio.sleep(0)
    assert response.status == 200
    assert response.content_type == "application/soap+xml"
    assert ACTION_SCAN_AVAILABLE_EVENT_RESPONSE in response.text
    assert "<wsa:RelatesTo>urn:uuid:req-1</wsa:RelatesTo>" in response.text
    assert calls == ["http://192.168.1.60:80/WSD/DEVICE"]


@pytest.mark.asyncio
async def test_audit_ws_scan_11_push_only_skips_retrieve_without_job_token(
    monkeypatch: MonkeyPatch,
) -> None:
    """``docs/ws-scan_audit.md`` §11 — push_only skips pull RetrieveImage even without JobToken."""
    retrieve_called = False

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, _minimal_gse_xml()
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return 200, _validate_ok_xml()
        if ACTION_CREATE_SCAN_JOB in payload:
            return (
                200,
                """<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-push</sca:JobId></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>""",
            )
        raise AssertionError("unexpected SOAP leg")

    async def fake_retrieve(
        **kwargs: object,
    ) -> tuple[int, bytes, str | None, HttpBodyIntegrityReport]:
        nonlocal retrieve_called
        retrieve_called = True
        raise AssertionError("RetrieveImage must not run in push_only mode")

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    monkeypatch.setattr("app.ws_eventing_client._post_soap_retrieve_image", fake_retrieve)

    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
        image_delivery_mode="push_only",
    )
    assert not retrieve_called
    assert result.get("pull_retrieve_skipped") == "push_only"
    assert result.get("retrieve_status") == "SkippedPushOnly"


def test_audit_ws_scan_17_parse_get_response_prefers_wdp_scan() -> None:
    """``docs/ws-scan_audit.md`` §17 — WS-Transfer Get parser prefers ``/WDP/SCAN`` URL."""
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body>
    <x:Info xmlns:x="urn:test">http://192.168.1.60:80/WDP/SCAN</x:Info>
    <x:Info xmlns:x="urn:test">http://192.168.1.60:80/WSDScanner</x:Info>
  </soap:Body>
</soap:Envelope>
"""
    parsed = parse_get_response(xml)
    assert parsed["suggested_subscribe_to_url"] == "http://192.168.1.60:80/WDP/SCAN"


@pytest.mark.asyncio
async def test_audit_ws_scan_16_handle_wsd_missing_config_returns_500(
    caplog: LogCaptureFixture,
) -> None:
    """``docs/ws-scan_audit.md`` §16 — mis-wired app config returns HTTP 500 without AttributeError."""
    caplog.set_level(logging.ERROR)
    response = await handle_wsd(
        _request_missing_config(_minimal_action_envelope(ACTION_SCAN_AVAILABLE_EVENT))
    )
    assert response.status == 500
    assert response.text == "Server configuration unavailable"
    assert any("missing valid config" in r.message for r in caplog.records)

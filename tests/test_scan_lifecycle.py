"""Tests for explicit scan lifecycle state machine (WIA spec §8)."""

from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch

from app.scan_lifecycle import (
    ScanLifecycle,
    ScanLifecycleState,
    ScanLifecycleStateViolation,
)
from app.soap.transport import HttpBodyIntegrityReport
from app.ws_eventing_client import (
    ACTION_CREATE_SCAN_JOB,
    ACTION_GET_SCANNER_ELEMENTS,
    ACTION_VALIDATE_SCAN_TICKET,
    run_scan_available_chain,
)

_DEFAULT_RETRIEVE_IMAGE_SUCCESS_XML = """<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse></soap:Body>
</soap:Envelope>"""


def test_happy_path_transitions() -> None:
    """Valid forward transitions follow spec §8 ordering."""
    lifecycle = ScanLifecycle()
    assert lifecycle.state == ScanLifecycleState.IDLE
    lifecycle.mark_discovered()
    lifecycle.mark_capabilities_loaded()
    lifecycle.mark_job_created("job-1")
    lifecycle.mark_polling()
    lifecycle.mark_retrieving()
    lifecycle.mark_completed()
    assert lifecycle.state == ScanLifecycleState.COMPLETED
    assert lifecycle.job_id == "job-1"
    assert "Idle" in lifecycle.path[0].value
    fields = lifecycle.enrich_result({})
    assert fields["lifecycle_state"] == "Completed"
    assert "Discovered" in fields["lifecycle_path"]
    assert fields["lifecycle_job_id"] == "job-1"


def test_invalid_transition_records_violation_not_strict() -> None:
    """Default mode logs violations without raising (chain orchestration stays tolerant)."""
    lifecycle = ScanLifecycle()
    lifecycle.mark_discovered()
    lifecycle.transition(ScanLifecycleState.RETRIEVING)
    assert lifecycle.violations
    assert lifecycle.state == ScanLifecycleState.DISCOVERED


def test_invalid_transition_raises_when_strict() -> None:
    """Strict mode surfaces violations to unit tests and debug tooling."""
    lifecycle = ScanLifecycle(strict=True)
    lifecycle.mark_discovered()
    with pytest.raises(ScanLifecycleStateViolation):
        lifecycle.transition(ScanLifecycleState.COMPLETED)


def test_terminal_state_rejects_further_transitions() -> None:
    """Completed chains cannot move back to active phases."""
    lifecycle = ScanLifecycle()
    lifecycle.mark_discovered()
    lifecycle.mark_capabilities_loaded()
    lifecycle.mark_job_created("j")
    lifecycle.mark_completed()
    lifecycle.transition(ScanLifecycleState.POLLING)
    assert "terminal" in lifecycle.violations[0]


@pytest.mark.asyncio
async def test_run_scan_available_chain_includes_lifecycle_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    """Integration: successful pull chain reports Completed lifecycle in result dict."""

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return (200, "<soap:Envelope><soap:Body/></soap:Envelope>")
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return (
                200,
                """<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status>
  <sca:ValidTicket>true</sca:ValidTicket></sca:ValidateScanTicketResponse></soap:Body></soap:Envelope>""",
            )
        if ACTION_CREATE_SCAN_JOB in payload:
            return (
                200,
                """<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>job-x</sca:JobId>
  <sca:JobToken>tok</sca:JobToken></sca:CreateScanJobResponse></soap:Body></soap:Envelope>""",
            )
        raise AssertionError(payload)

    async def fake_retrieve(*, url: str, payload: str, timeout_sec: float) -> tuple[
        int, bytes, str | None, HttpBodyIntegrityReport
    ]:
        raw = _DEFAULT_RETRIEVE_IMAGE_SUCCESS_XML.encode()
        return (
            200,
            raw,
            "application/soap+xml",
            HttpBodyIntegrityReport(ok=True, body_len=len(raw), content_length=len(raw)),
        )

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    monkeypatch.setattr("app.ws_eventing_client._post_soap_retrieve_image", fake_retrieve)

    result = await run_scan_available_chain(
        scanner_xaddr="http://scanner/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
    )
    assert result["lifecycle_state"] == "Completed"
    assert result["lifecycle_job_id"] == "job-x"
    assert "Retrieving" in (result.get("lifecycle_path") or "")
    assert "CapabilitiesLoaded" in (result.get("lifecycle_path") or "")


@pytest.mark.asyncio
async def test_run_scan_available_chain_validation_failure_lifecycle_error(
    monkeypatch: MonkeyPatch,
) -> None:
    """ValidateScanTicket failure ends in Error lifecycle state."""

    async def fake_metadata(**_kwargs: object) -> dict[str, str]:
        return {"status": "200"}

    async def fake_post(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return (
                200,
                """<soap:Envelope xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><wscn:ValidateScanTicketResponse><wscn:ValidationInfo>
  <wscn:ValidTicket>false</wscn:ValidTicket></wscn:ValidationInfo></wscn:ValidateScanTicketResponse></soap:Body></soap:Envelope>""",
            )
        raise AssertionError(payload)

    monkeypatch.setattr(
        "app.ws_eventing_client.get_scanner_elements_metadata",
        fake_metadata,
    )
    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post)
    result = await run_scan_available_chain(
        scanner_xaddr="http://scanner/WSD/DEVICE",
    )
    assert result["lifecycle_state"] == "Error"
    assert "Error" in (result.get("lifecycle_path") or "")

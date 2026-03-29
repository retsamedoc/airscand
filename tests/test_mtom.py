"""Tests for MTOM multipart RetrieveImage parsing."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from app.mtom import (
    extract_xop_include_cid,
    normalize_cid,
    parse_retrieve_image_mtom,
)
from app.ws_eventing_client import (
    ACTION_CREATE_SCAN_JOB,
    ACTION_GET_SCANNER_ELEMENTS,
    ACTION_RETRIEVE_IMAGE,
    ACTION_VALIDATE_SCAN_TICKET,
    run_scan_available_chain,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_EPSON_SOAP = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wscn="http://schemas.microsoft.com/windows/2006/08/wdp/scan"
  xmlns:xop="http://www.w3.org/2004/08/xop/include">
<soap:Header><wsa:Action>http://schemas.microsoft.com/windows/2006/08/wdp/scan/RetrieveImageResponse</wsa:Action></soap:Header>
<soap:Body><wscn:RetrieveImageResponse><wscn:ScanData>
<xop:Include href="cid:9CAED324E3C0_417441432@epson"/>
</wscn:ScanData></wscn:RetrieveImageResponse></soap:Body></soap:Envelope>"""

_JPEG_PREFIX = b"\xff\xd8\xff\xe0"


def _build_mtom_http_body(*, boundary: str, soap_xml: str, image_bytes: bytes, cid: str) -> bytes:
    """Build a minimal multipart/related body (RFC-style CRLF) for tests."""
    chunks: list[bytes] = []
    chunks.append(f"--{boundary}\r\n".encode("ascii"))
    chunks.append(b"Content-Type: application/xop+xml\r\n\r\n")
    chunks.append(soap_xml.encode("utf-8"))
    chunks.append(f"\r\n--{boundary}\r\n".encode("ascii"))
    chunks.append(
        f"Content-Type:image/jpeg\r\nContent-Transfer-Encoding:binary\r\nContent-ID:<{cid}>\r\n\r\n".encode(
            "ascii"
        )
    )
    chunks.append(image_bytes)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)


def test_normalize_cid_matches_angle_and_cid_prefix() -> None:
    """Content-ID header form matches ``cid:`` reference."""
    assert normalize_cid("cid:9CAED324E3C0_417441432@epson") == normalize_cid(
        "<9CAED324E3C0_417441432@epson>"
    )


def test_extract_xop_include_cid_finds_href() -> None:
    """Parser reads the cid token from Epson-style ``xop:Include``."""
    cid = extract_xop_include_cid(_EPSON_SOAP)
    assert cid == "9CAED324E3C0_417441432@epson"


def test_parse_retrieve_image_mtom_extracts_jpeg() -> None:
    """MTOM response yields SOAP text plus image bytes and part Content-Type."""
    boundary = "mime_boundary_test_1"
    outer_ct = f'multipart/related; type="application/xop+xml"; boundary="{boundary}"'
    body = _build_mtom_http_body(
        boundary=boundary,
        soap_xml=_EPSON_SOAP,
        image_bytes=_JPEG_PREFIX + b"data",
        cid="9CAED324E3C0_417441432@epson",
    )
    soap_text, image_bytes, image_ct = parse_retrieve_image_mtom(body, outer_ct)
    assert "RetrieveImageResponse" in soap_text
    assert image_bytes == _JPEG_PREFIX + b"data"
    assert image_ct is not None and "jpeg" in image_ct.lower()


def test_parse_retrieve_image_mtom_non_multipart_returns_soap_only() -> None:
    """Plain SOAP XML responses leave image bytes unset."""
    xml = (
        '<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">'
        "<soap:Body><sca:RetrieveImageResponse><sca:Status>Success</sca:Status></sca:RetrieveImageResponse>"
        "</soap:Body></soap:Envelope>"
    )
    soap_text, image_bytes, image_ct = parse_retrieve_image_mtom(
        xml.encode("utf-8"), "application/soap+xml"
    )
    assert "Success" in soap_text
    assert image_bytes is None
    assert image_ct is None


@pytest.mark.asyncio
async def test_run_scan_available_chain_saves_mtom_image(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """When the scanner returns MTOM, image bytes are written under ``output_dir``."""
    calls: list[str] = []
    boundary = "b_mtom_save"
    outer_ct = f'multipart/related; type="application/xop+xml"; boundary="{boundary}"'
    mtom_body = _build_mtom_http_body(
        boundary=boundary,
        soap_xml=_EPSON_SOAP,
        image_bytes=_JPEG_PREFIX + b"x",
        cid="9CAED324E3C0_417441432@epson",
    )

    async def fake_post_soap(*, url: str, payload: str, timeout_sec: float) -> tuple[int, str]:
        calls.append(payload)
        if ACTION_GET_SCANNER_ELEMENTS in payload:
            return 200, "<soap:Envelope/>"
        if ACTION_VALIDATE_SCAN_TICKET in payload:
            return (
                200,
                """<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:ValidateScanTicketResponse><sca:Status>Success</sca:Status></sca:ValidateScanTicketResponse></soap:Body>
</soap:Envelope>""",
            )
        if ACTION_CREATE_SCAN_JOB in payload:
            return (
                200,
                """<soap:Envelope xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <soap:Body><sca:CreateScanJobResponse><sca:JobId>j1</sca:JobId><sca:JobToken>t1</sca:JobToken></sca:CreateScanJobResponse></soap:Body>
</soap:Envelope>""",
            )
        raise AssertionError("unexpected SOAP request")

    async def fake_post_soap_retrieve_image(
        *, url: str, payload: str, timeout_sec: float
    ) -> tuple[int, bytes, str | None]:
        assert ACTION_RETRIEVE_IMAGE in payload
        return (200, mtom_body, outer_ct)

    monkeypatch.setattr("app.ws_eventing_client._post_soap", fake_post_soap)
    monkeypatch.setattr(
        "app.ws_eventing_client._post_soap_retrieve_image", fake_post_soap_retrieve_image
    )
    monkeypatch.setattr("app.scan_storage.uuid.uuid4", lambda: "mtom-test-id")

    result = await run_scan_available_chain(
        scanner_xaddr="http://192.168.1.60:80/WSD/DEVICE",
        poll_get_job_status_before_retrieve=False,
        output_dir=tmp_path,
    )
    assert result.get("retrieve_http_status") == "200"
    assert result.get("saved_scan_path") == str(tmp_path / "scan_mtom-test-id.jpg")
    assert result.get("saved_scan_bytes") == str(len(_JPEG_PREFIX + b"x"))
    saved = tmp_path / "scan_mtom-test-id.jpg"
    assert saved.read_bytes() == _JPEG_PREFIX + b"x"
    assert len(calls) == 3

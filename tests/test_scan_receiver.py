"""Scan receiver persistence and validation tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from app.config import Config
from app.scan_receiver import detect_file_type, handle_scan

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


class DummyRequest:
    """Minimal aiohttp-like request object for unit testing."""

    def __init__(
        self,
        *,
        body: bytes,
        app_data: dict[str, Any],
        content_type: str = "application/octet-stream",
    ) -> None:
        """Store request shape expected by the scan handler."""
        self._body = body
        self.app = app_data
        self.content_type = content_type
        self.content_length = len(body)

    async def read(self) -> bytes:
        """Return request body bytes."""
        return self._body


def _test_config(output_dir: Path) -> Config:
    """Create Config instance without environment side effects."""
    config = Config.__new__(Config)
    config.output_dir = str(output_dir)
    return config


def test_detect_file_type_jpg() -> None:
    """JPEG signature is detected as jpg extension."""
    assert detect_file_type(b"\xff\xd8\xff\xe0abc") == "jpg"


def test_detect_file_type_pdf() -> None:
    """PDF signature is detected as pdf extension."""
    assert detect_file_type(b"%PDF-1.7") == "pdf"


def test_detect_file_type_unknown() -> None:
    """Unknown content falls back to bin extension."""
    assert detect_file_type(b"\x00\x01\x02") == "bin"


@pytest.mark.asyncio
async def test_handle_scan_persists_payload(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Scan payload is saved to output directory with detected extension."""
    monkeypatch.setattr("app.scan_receiver.uuid.uuid4", lambda: "fixed-id")
    config = _test_config(tmp_path)
    request = DummyRequest(
        body=b"%PDF-1.7\nbinary-data",
        app_data={"config": config},
        content_type="application/pdf",
    )

    response = await handle_scan(request)
    assert response.status == 201
    output = tmp_path / "scan_fixed-id.pdf"
    assert output.exists()
    assert output.read_bytes() == b"%PDF-1.7\nbinary-data"


@pytest.mark.asyncio
async def test_handle_scan_rejects_empty_payload(tmp_path: Path) -> None:
    """Empty request payloads are rejected with bad request."""
    config = _test_config(tmp_path)
    request = DummyRequest(body=b"", app_data={"config": config})

    response = await handle_scan(request)
    assert response.status == 400
    assert response.text == "Empty scan payload"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_handle_scan_invalid_config_returns_server_error() -> None:
    """Missing valid config object returns server error response."""
    request = DummyRequest(body=b"abc", app_data={})
    response = await handle_scan(request)
    assert response.status == 500
    assert response.text == "Server configuration unavailable"

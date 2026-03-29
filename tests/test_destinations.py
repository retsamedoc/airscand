"""Tests for scan destinations and ticket helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.destinations import (
    DEFAULT_DESTINATIONS,
    ScanDestination,
    ScanDestinationConfig,
    lookup_destination,
    subscribe_tuple_destinations,
)
from app.soap.parsers.capabilities import parse_scanner_capabilities
from app.soap.parsers.scan import (
    SCAN_TICKET_TEMPLATE_XML,
    build_scan_ticket_from_destination_config,
    validate_scan_ticket_against_capabilities,
)

# Same minimal device XML as ``tests.test_capabilities._MINIMAL_PLATEN_XML``.
_MINIMAL_PLATEN_XML = """
<sca:ScannerConfiguration xmlns:sca="http://schemas.microsoft.com/windows/2006/08/wdp/scan">
  <sca:Platen>true</sca:Platen>
  <sca:PlatenSpecifications>
    <sca:OpticalResolutions>
      <sca:Width>300</sca:Width><sca:Height>300</sca:Height>
      <sca:Width>600</sca:Width><sca:Height>600</sca:Height>
    </sca:OpticalResolutions>
    <sca:ColorEntries>
      <sca:ColorEntry>RGB24</sca:ColorEntry>
      <sca:ColorEntry>Grayscale8</sca:ColorEntry>
    </sca:ColorEntries>
    <sca:MinSize>
      <sca:Width>100</sca:Width>
      <sca:Height>100</sca:Height>
    </sca:MinSize>
    <sca:MaxSize>
      <sca:Width>8500</sca:Width>
      <sca:Height>11700</sca:Height>
    </sca:MaxSize>
  </sca:PlatenSpecifications>
  <sca:ADF>false</sca:ADF>
</sca:ScannerConfiguration>
"""


def test_lookup_destination_matches_client_context() -> None:
    """ClientContext selects the matching destination."""
    d1 = ScanDestination("A", "Scan")
    d2 = ScanDestination("B", "ScanToEmail")
    assert lookup_destination("ScanToEmail", (d1, d2)) is d2


def test_lookup_destination_falls_back_to_first() -> None:
    """Unknown context falls back to the first destination."""
    d1 = ScanDestination("A", "Scan")
    d2 = ScanDestination("B", "ScanToEmail")
    assert lookup_destination("Unknown", (d1, d2)) is d1


def test_lookup_destination_empty_context_uses_first() -> None:
    """Missing context uses the first entry."""
    d1 = ScanDestination("A", "Scan")
    d2 = ScanDestination("B", "X")
    assert lookup_destination(None, (d1, d2)) is d1
    assert lookup_destination("", (d1, d2)) is d1


def test_subscribe_tuple_destinations_matches_default_scan_destinations() -> None:
    """Subscribe tuples align with ``DEFAULT_DESTINATIONS``."""
    tuples = subscribe_tuple_destinations(DEFAULT_DESTINATIONS)
    assert tuples[0] == (
        DEFAULT_DESTINATIONS[0].display_name,
        DEFAULT_DESTINATIONS[0].client_context,
    )


def test_build_scan_ticket_from_destination_config_uses_clamped_dpi() -> None:
    """Destination config produces a ticket with clamped resolution."""
    caps = parse_scanner_capabilities(_MINIMAL_PLATEN_XML)
    cfg = ScanDestinationConfig(dpi_width=500, dpi_height=500, input_source="Platen")
    xml = build_scan_ticket_from_destination_config(cfg, caps)
    assert "<sca:Width>600</sca:Width>" in xml
    assert "<sca:Height>600</sca:Height>" in xml
    assert "Platen" in xml


def test_validate_scan_ticket_flags_bad_resolution() -> None:
    """Validation reports when ticket resolution is not in the device list."""
    caps = parse_scanner_capabilities(_MINIMAL_PLATEN_XML)
    out_ok = validate_scan_ticket_against_capabilities(SCAN_TICKET_TEMPLATE_XML, caps)
    assert out_ok["ok"] is True
    ticket_bad = SCAN_TICKET_TEMPLATE_XML.replace(
        "<sca:Width>300</sca:Width>",
        "<sca:Width>9999</sca:Width>",
        1,
    ).replace(
        "<sca:Height>300</sca:Height>",
        "<sca:Height>9999</sca:Height>",
        1,
    )
    out_bad = validate_scan_ticket_against_capabilities(ticket_bad, caps)
    assert out_bad["ok"] is False
    assert any("resolution_not_listed" in x for x in (out_bad.get("issues") or []))


def test_save_scan_file_subdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional subdir places files under a nested folder."""
    from app.scan_storage import save_scan_file

    monkeypatch.setattr("app.scan_storage.uuid.uuid4", lambda: "test-id")
    path_base = save_scan_file(tmp_path, b"\xff\xd8")
    assert path_base == tmp_path / "scan_test-id.jpg"
    path_nested = save_scan_file(tmp_path, b"\xff\xd8", subdir="photos")
    assert path_nested == tmp_path / "photos" / "scan_test-id.jpg"
    assert path_nested.read_bytes() == b"\xff\xd8"

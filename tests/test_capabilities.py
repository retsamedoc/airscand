"""Tests for ``ScannerConfiguration`` capability parsing."""

from __future__ import annotations

from app.soap.parsers.capabilities import (
    clamp_resolution_to_capabilities,
    parse_scanner_capabilities,
    pick_color_entry,
)

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


def test_parse_scanner_capabilities_returns_none_for_empty() -> None:
    """Empty or missing XML yields None."""
    assert parse_scanner_capabilities(None) is None
    assert parse_scanner_capabilities("") is None
    assert parse_scanner_capabilities("   ") is None


def test_parse_scanner_capabilities_platen_resolutions_and_colors() -> None:
    """Platen specifications expose resolutions, colors, and size bounds."""
    caps = parse_scanner_capabilities(_MINIMAL_PLATEN_XML)
    assert caps is not None
    assert caps.platen is not None
    assert caps.platen.enabled is True
    assert (300, 300) in caps.platen.resolutions
    assert (600, 600) in caps.platen.resolutions
    assert "RGB24" in caps.platen.color_entries
    assert caps.platen.min_width == 100
    assert caps.platen.max_width == 8500


def test_parse_scanner_capabilities_platen_only_flag_no_specs() -> None:
    """Platen enabled without a specifications block still parses."""
    xml = "<sca:ScannerConfiguration><sca:Platen>true</sca:Platen></sca:ScannerConfiguration>"
    caps = parse_scanner_capabilities(xml)
    assert caps is not None
    assert caps.platen is not None
    assert caps.platen.enabled is True
    assert caps.platen.resolutions == ()


def test_clamp_resolution_picks_nearest_pair() -> None:
    """Requested DPI snaps to the closest advertised pair."""
    caps = parse_scanner_capabilities(_MINIMAL_PLATEN_XML)
    assert caps is not None and caps.platen is not None
    assert clamp_resolution_to_capabilities(301, 299, caps.platen) == (300, 300)
    assert clamp_resolution_to_capabilities(600, 600, caps.platen) == (600, 600)


def test_pick_color_entry_falls_back_to_first() -> None:
    """Unknown color falls back to the first listed entry."""
    caps = parse_scanner_capabilities(_MINIMAL_PLATEN_XML)
    assert caps is not None and caps.platen is not None
    assert pick_color_entry("RGB24", caps.platen) == "RGB24"
    assert pick_color_entry("NoSuchMode", caps.platen) == "RGB24"

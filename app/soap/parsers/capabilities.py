"""Parse ``ScannerConfiguration`` XML from GetScannerElements for capability validation."""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "InputSourceCapabilities",
    "ScannerCapabilities",
    "clamp_resolution_to_capabilities",
    "input_source_capabilities_for_name",
    "parse_scanner_capabilities",
    "pick_color_entry",
]


@dataclass(frozen=True)
class InputSourceCapabilities:
    """Per-input-source limits advertised in ``ScannerConfiguration``."""

    enabled: bool
    resolutions: tuple[tuple[int, int], ...]
    color_entries: tuple[str, ...]
    min_width: int | None
    min_height: int | None
    max_width: int | None
    max_height: int | None


@dataclass(frozen=True)
class ScannerCapabilities:
    """Aggregated scanner limits from ``ScannerConfiguration``."""

    platen: InputSourceCapabilities | None
    adf: InputSourceCapabilities | None
    feeder: InputSourceCapabilities | None


_SPECS_BLOCK_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?(?P<block>PlatenSpecifications|ADFSpecifications|FeederSpecifications)"
    r"\b[^>]*>(?P<inner>.*?)</(?:[A-Za-z0-9_]+:)?(?P=block)>",
    re.DOTALL | re.IGNORECASE,
)
_OPTICAL_RES_INNER_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?OpticalResolutions\b[^>]*>(?P<inner>.*?)</(?:[A-Za-z0-9_]+:)?OpticalResolutions>",
    re.DOTALL | re.IGNORECASE,
)
_WIDTH_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Width>\s*(\d+)\s*</(?:[A-Za-z0-9_]+:)?Width>",
    re.IGNORECASE,
)
_HEIGHT_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?Height>\s*(\d+)\s*</(?:[A-Za-z0-9_]+:)?Height>",
    re.IGNORECASE,
)
_COLOR_ENTRY_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?ColorEntry>\s*([^<]+?)\s*</(?:[A-Za-z0-9_]+:)?ColorEntry>",
    re.IGNORECASE,
)
_SIZE_BLOCK_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?(?P<tag>MinSize|MaxSize)\b[^>]*>(?P<inner>.*?)</(?:[A-Za-z0-9_]+:)?(?P=tag)>",
    re.DOTALL | re.IGNORECASE,
)


def _enabled_from_xml(xml: str, name: str) -> bool:
    """Return True when ``<Platen>`` / ``<ADF>`` / ``<Feeder>`` is explicitly true."""
    pat = re.compile(
        rf"<(?:[A-Za-z0-9_]+:)?{re.escape(name)}\b[^>]*>\s*true\s*</",
        re.IGNORECASE,
    )
    return bool(pat.search(xml))


def _parse_width_height_pairs(block: str) -> tuple[tuple[int, int], ...]:
    """Pair sequential Width/Height elements (common in OpticalResolutions)."""
    widths = [int(m.group(1)) for m in _WIDTH_PATTERN.finditer(block)]
    heights = [int(m.group(1)) for m in _HEIGHT_PATTERN.finditer(block)]
    if len(widths) != len(heights) or not widths:
        return ()
    return tuple(zip(widths, heights, strict=True))


def _parse_size_dimensions(block: str) -> tuple[int | None, int | None]:
    """First Width/Height inside a MinSize or MaxSize block."""
    wm = _WIDTH_PATTERN.search(block)
    hm = _HEIGHT_PATTERN.search(block)
    w = int(wm.group(1)) if wm else None
    h = int(hm.group(1)) if hm else None
    return (w, h)


def _parse_specs_block(inner: str) -> InputSourceCapabilities:
    """Build capabilities from a *Specifications inner XML fragment."""
    opt_m = _OPTICAL_RES_INNER_PATTERN.search(inner)
    opt_inner = opt_m.group("inner") if opt_m else inner
    resolutions = _parse_width_height_pairs(opt_inner)

    colors = tuple(
        c.strip()
        for c in _COLOR_ENTRY_PATTERN.findall(inner)
        if c.strip()
    )

    min_w = min_h = max_w = max_h = None
    for sm in _SIZE_BLOCK_PATTERN.finditer(inner):
        tag = (sm.group("tag") or "").strip()
        dims = _parse_size_dimensions(sm.group("inner") or "")
        w, h = dims
        if tag.lower() == "minsize":
            min_w, min_h = w, h
        elif tag.lower() == "maxsize":
            max_w, max_h = w, h

    return InputSourceCapabilities(
        enabled=True,
        resolutions=resolutions,
        color_entries=colors,
        min_width=min_w,
        min_height=min_h,
        max_width=max_w,
        max_height=max_h,
    )


def _capabilities_for_source(
    full_xml: str,
    specs_name: str,
    source_enabled_name: str,
) -> InputSourceCapabilities | None:
    """Resolve one input source: enabled flag + optional specifications block."""
    enabled = _enabled_from_xml(full_xml, source_enabled_name)
    block_m = None
    for m in _SPECS_BLOCK_PATTERN.finditer(full_xml):
        if (m.group("block") or "").lower() == specs_name.lower():
            block_m = m
            break
    if block_m:
        caps = _parse_specs_block(block_m.group("inner") or "")
        return InputSourceCapabilities(
            enabled=enabled and caps.enabled,
            resolutions=caps.resolutions,
            color_entries=caps.color_entries,
            min_width=caps.min_width,
            min_height=caps.min_height,
            max_width=caps.max_width,
            max_height=caps.max_height,
        )
    if not enabled:
        return InputSourceCapabilities(
            enabled=False,
            resolutions=(),
            color_entries=(),
            min_width=None,
            min_height=None,
            max_width=None,
            max_height=None,
        )
    return InputSourceCapabilities(
        enabled=True,
        resolutions=(),
        color_entries=(),
        min_width=None,
        min_height=None,
        max_width=None,
        max_height=None,
    )


def parse_scanner_capabilities(scanner_configuration_xml: str | None) -> ScannerCapabilities | None:
    """Parse ``ScannerConfiguration`` element XML into structured capabilities.

    Args:
        scanner_configuration_xml: Raw XML of the ``ScannerConfiguration`` element, or None.

    Returns:
        Parsed capabilities, or None when input is empty or unusable.
    """
    if not (scanner_configuration_xml and scanner_configuration_xml.strip()):
        return None
    xml = scanner_configuration_xml.strip()
    platen = _capabilities_for_source(xml, "PlatenSpecifications", "Platen")
    adf = _capabilities_for_source(xml, "ADFSpecifications", "ADF")
    feeder = _capabilities_for_source(xml, "FeederSpecifications", "Feeder")
    return ScannerCapabilities(platen=platen, adf=adf, feeder=feeder)


def input_source_capabilities_for_name(
    caps: ScannerCapabilities | None,
    input_source: str,
) -> InputSourceCapabilities | None:
    """Select ``InputSourceCapabilities`` for a ticket ``InputSource`` value."""
    if caps is None:
        return None
    key = (input_source or "").strip().lower()
    if key == "platen":
        return caps.platen
    if key == "adf":
        return caps.adf
    if key == "feeder":
        return caps.feeder
    return None


def clamp_resolution_to_capabilities(
    width_dpi: int,
    height_dpi: int,
    source_caps: InputSourceCapabilities | None,
) -> tuple[int, int]:
    """Clamp requested DPI to the nearest supported resolution pair when data exists."""
    if source_caps is None or not source_caps.resolutions:
        return (width_dpi, height_dpi)
    pairs = source_caps.resolutions
    if (width_dpi, height_dpi) in pairs:
        return (width_dpi, height_dpi)

    def dist(a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    best = min(pairs, key=lambda p: dist(p, (width_dpi, height_dpi)))
    return (best[0], best[1])


def pick_color_entry(
    requested: str,
    source_caps: InputSourceCapabilities | None,
) -> str:
    """Return ``requested`` if allowed; otherwise the first advertised color entry."""
    if source_caps is None or not source_caps.color_entries:
        return requested
    req = requested.strip()
    if req in source_caps.color_entries:
        return req
    return source_caps.color_entries[0]

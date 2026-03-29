"""Scan destination registry: display names, client contexts, and optional scan parameters."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

__all__ = [
    "DEFAULT_DESTINATIONS",
    "PostProcessingHook",
    "ScanDestination",
    "ScanDestinationConfig",
    "lookup_destination",
    "subscribe_tuple_destinations",
]


class PostProcessingHook(Protocol):
    """Optional post-save hook (e.g. auto-crop, rotate); invoked with the saved file path."""

    def __call__(self, path: Path) -> None:
        """Run after a scan file is written."""
        ...


@dataclass(frozen=True)
class ScanDestinationConfig:
    """Per-destination WS-Scan ticket defaults (1/1000 inch for sizes, DPI for resolution)."""

    dpi_width: int = 300
    dpi_height: int = 300
    color_processing: str = "RGB24"
    format: str = "exif"
    input_source: str = "Platen"
    paper_width: int = 8500
    paper_height: int = 11700
    output_subdir: str | None = None


@dataclass
class ScanDestination:
    """One logical sink advertised in Subscribe and matched by ``ScanAvailableEvent`` context."""

    display_name: str
    client_context: str
    config: ScanDestinationConfig | None = None
    post_processing_hooks: list[PostProcessingHook] = field(default_factory=list)


DEFAULT_DESTINATIONS: tuple[ScanDestination, ...] = (
    ScanDestination("Scan to airscand", "Scan"),
    ScanDestination("Scan for Print to airscand", "ScanToPrint"),
    ScanDestination("Scan for E-mail to airscand", "ScanToEmail"),
    ScanDestination("Scan for Fax to airscand", "ScanToFax"),
    ScanDestination("Scan for OCR to airscand", "ScanToOCR"),
)


def lookup_destination(
    client_context: str | None,
    destinations: Sequence[ScanDestination],
) -> ScanDestination | None:
    """Resolve a destination by ``ClientContext``, falling back to the first entry."""
    if not destinations:
        return None
    cc = (client_context or "").strip()
    if not cc:
        return destinations[0]
    for dest in destinations:
        if dest.client_context == cc:
            return dest
    return destinations[0]


def subscribe_tuple_destinations(
    destinations: Sequence[ScanDestination],
) -> tuple[tuple[str, str], ...]:
    """``(ClientDisplayName, ClientContext)`` tuples for WS-Eventing Subscribe bodies."""
    return tuple((d.display_name, d.client_context) for d in destinations)

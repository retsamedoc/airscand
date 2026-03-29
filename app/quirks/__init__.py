"""Scanner vendor profiles for WS-Scan interoperability.

Shared types and the **generic** profile live here. Vendor-specific profiles live under
``app/quirks/<vendor>.py`` (e.g. :mod:`app.quirks.epson`) and are registered below for
:func:`get_profile`.

See ``docs/protocol/vendor_quirks.md`` and ``docs/ROADMAP.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

__all__ = [
    "ScannerProfile",
    "PROFILE_GENERIC",
    "PROFILE_EPSON_WF_3640",
    "get_profile",
]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannerProfile:
    """Resolved scanner profile; optional fields override outbound scan chain defaults."""

    key: str
    description: str = ""
    # When False, skip GetJobStatus polling before RetrieveImage (device does not implement it reliably).
    poll_get_job_status_before_retrieve: bool = True
    # aiohttp total timeout for RetrieveImage MTOM/chunked body read (seconds).
    retrieve_image_timeout_sec: float = 5.0


PROFILE_GENERIC = ScannerProfile(
    key="generic",
    description="Default interoperability profile (no vendor-specific overrides).",
)

from .epson import PROFILE_EPSON_WF_3640

_PROFILES: dict[str, ScannerProfile] = {
    PROFILE_GENERIC.key: PROFILE_GENERIC,
    PROFILE_EPSON_WF_3640.key: PROFILE_EPSON_WF_3640,
    # Convenience alias
    "epson": PROFILE_EPSON_WF_3640,
}


def _normalize_profile_key(raw: str) -> str:
    """Normalize user/config profile key for registry lookup."""
    return raw.strip().lower().replace("-", "_")


def get_profile(key: str) -> ScannerProfile:
    """Return the registered profile for ``key``, or generic with a warning if unknown."""
    norm = _normalize_profile_key(key)
    if not norm:
        return PROFILE_GENERIC
    resolved = _PROFILES.get(norm)
    if resolved is not None:
        return resolved
    log.warning(
        "Unknown scanner profile %r; using generic",
        key,
        extra={"scanner_profile_key": key, "fallback": PROFILE_GENERIC.key},
    )
    return PROFILE_GENERIC

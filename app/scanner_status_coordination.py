"""In-process coordination between outbound RetrieveImage and inbound ScannerStatusSummaryEvent.

``ScannerStatusSummaryEvent`` carries global ``ScannerState`` (not job-scoped). While a pull chain
is active, we wait for ``Idle`` after a successful ``RetrieveImage`` HTTP response using a single
in-flight event (see plan: single-flight assumption for device-initiated scans).
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

_post_retrieve_idle_event: asyncio.Event | None = None


def begin_retrieve_idle_wait() -> None:
    """Create a fresh event before sending ``RetrieveImage`` so Idle can arrive during the HTTP wait."""
    global _post_retrieve_idle_event
    _post_retrieve_idle_event = asyncio.Event()


def end_retrieve_idle_wait() -> None:
    """Clear the active Idle wait (call from ``finally`` after retrieve + optional Idle wait)."""
    global _post_retrieve_idle_event
    _post_retrieve_idle_event = None


def notify_scanner_state(scanner_state: str | None) -> None:
    """If ``scanner_state`` is Idle, signal the current post-retrieve Idle wait."""
    if not scanner_state:
        return
    if scanner_state.strip().lower() != "idle":
        return
    ev = _post_retrieve_idle_event
    if ev is not None and not ev.is_set():
        ev.set()
        log.debug(
            "ScannerStatusSummaryEvent signaled Idle for post-retrieve wait",
            extra={"scanner_state": scanner_state.strip()},
        )


async def await_scanner_idle_after_retrieve(timeout_sec: float) -> bool:
    """Wait for Idle after ``begin_retrieve_idle_wait``; returns False on timeout."""
    ev = _post_retrieve_idle_event
    if ev is None:
        return False
    try:
        await asyncio.wait_for(ev.wait(), timeout=timeout_sec)
        return True
    except asyncio.TimeoutError:
        log.warning(
            "Timed out waiting for ScannerStatusSummaryEvent Idle after RetrieveImage",
            extra={"timeout_sec": timeout_sec},
        )
        return False

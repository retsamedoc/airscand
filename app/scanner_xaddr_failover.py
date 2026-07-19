"""Ordered WS-Discovery XAddr rotation for outbound SOAP transport failures.

Registration already advances through ProbeMatches candidates on connect/timeout errors.
Scan-chain legs reuse the same classifier and logging shape so operators can grep one set of
fields across registration and mid-job failover.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.soap.parsers.scan import resolve_wdp_scan_url
from app.soap.transport import is_scanner_xaddr_transport_failover

log = logging.getLogger(__name__)


def normalize_scanner_xaddr_candidates(
    scanner_xaddr: str,
    candidates: Sequence[str] | None = None,
) -> list[str]:
    """Build a non-empty ordered candidate list for scan-chain failover.

    Args:
        scanner_xaddr: Active scanner device XAddr (registration winner or override).
        candidates: Optional ProbeMatches-ordered list persisted at registration.

    Returns:
        Deduplicated ordered URLs; always includes ``scanner_xaddr`` when non-empty.
    """
    active = str(scanner_xaddr or "").strip()
    raw: list[str] = []
    if candidates:
        raw.extend(str(c).strip() for c in candidates if str(c).strip())
    if active and active not in raw:
        raw.insert(0, active)
    if not raw and active:
        raw = [active]
    # Preserve order while dropping duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for url in raw:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


@dataclass
class ScannerXAddrRotator:
    """Track the active ProbeMatches XAddr and advance on transport-layer failures."""

    candidates: list[str]
    active_index: int = 0
    failover_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("ScannerXAddrRotator requires at least one XAddr candidate")
        if self.active_index < 0 or self.active_index >= len(self.candidates):
            self.active_index = 0

    @classmethod
    def from_scanner_xaddr(
        cls,
        scanner_xaddr: str,
        candidates: Sequence[str] | None = None,
    ) -> ScannerXAddrRotator:
        """Construct a rotator from the active XAddr and optional discovery list."""
        normalized = normalize_scanner_xaddr_candidates(scanner_xaddr, candidates)
        if not normalized:
            raise ValueError("scanner_xaddr and candidates are both empty")
        preferred = str(scanner_xaddr or "").strip()
        start = normalized.index(preferred) if preferred in normalized else 0
        return cls(candidates=normalized, active_index=start)

    @property
    def scanner_xaddr(self) -> str:
        """Return the active device XAddr."""
        return self.candidates[self.active_index]

    @property
    def target_url(self) -> str:
        """Return the WDP/SCAN SOAP URL derived from the active XAddr."""
        return resolve_wdp_scan_url(self.scanner_xaddr)

    @property
    def candidates_total(self) -> int:
        """Return the number of ordered candidates."""
        return len(self.candidates)

    def remaining_after_active(self) -> int:
        """Return how many candidates remain after the current index."""
        return max(0, len(self.candidates) - self.active_index - 1)

    def log_extra(self) -> dict[str, object]:
        """Return structured log fields mirroring registration failover."""
        return {
            "scanner_xaddr": self.scanner_xaddr,
            "xaddr_attempt_index": self.active_index,
            "xaddr_candidates_total": self.candidates_total,
        }

    def log_try(self, *, context: str, operation: str) -> None:
        """Log an outbound attempt against the active XAddr."""
        log.info(
            "Scan chain trying discovered XAddr"
            if context == "scan_chain"
            else "Scanner registration trying discovered XAddr",
            extra={
                **self.log_extra(),
                "xaddr_failover_context": context,
                "soap_operation": operation,
            },
        )

    def can_failover(self, exc: BaseException) -> bool:
        """Return True when ``exc`` warrants trying the next XAddr and one remains."""
        return is_scanner_xaddr_transport_failover(exc) and self.remaining_after_active() > 0

    def advance(self, exc: BaseException, *, context: str, operation: str) -> bool:
        """Advance to the next candidate after a transport failure.

        Args:
            exc: Exception raised by the failed outbound call.
            context: ``registration`` or ``scan_chain`` for log correlation.
            operation: SOAP operation name (e.g. ``ValidateScanTicket``).

        Returns:
            True when a next candidate is now active; False when exhausted or
            ``exc`` is not a transport failover case (index unchanged).
        """
        if not self.can_failover(exc):
            return False
        log.warning(
            "Scanner XAddr unreachable during scan chain; trying next candidate"
            if context == "scan_chain"
            else "Scanner XAddr unreachable during registration; trying next candidate",
            extra={
                **self.log_extra(),
                "xaddr_failover_context": context,
                "soap_operation": operation,
                "error": str(exc),
            },
        )
        self.active_index += 1
        self.failover_count += 1
        return True

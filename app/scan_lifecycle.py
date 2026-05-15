"""Explicit scan lifecycle state machine (WIA client spec §8).

Why: ``run_scan_available_chain`` previously encoded phase order only implicitly in
control flow. Named states and transition guards make invalid sequencing visible in
logs and chain results without changing SOAP behavior on the happy path.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Final

log = logging.getLogger(__name__)


class ScanLifecycleState(StrEnum):
    """Per-chain client states aligned with ``docs/protocol/wia_client_spec.md`` §8."""

    IDLE = "Idle"
    DISCOVERED = "Discovered"
    CAPABILITIES_LOADED = "CapabilitiesLoaded"
    JOB_CREATED = "JobCreated"
    POLLING = "Polling"
    RETRIEVING = "Retrieving"
    COMPLETED = "Completed"
    ERROR = "Error"
    CANCELLED = "Cancelled"


TERMINAL_STATES = frozenset(
    {
        ScanLifecycleState.COMPLETED,
        ScanLifecycleState.ERROR,
        ScanLifecycleState.CANCELLED,
    }
)

_ALLOWED: Final[dict[ScanLifecycleState, frozenset[ScanLifecycleState]]] = {
    ScanLifecycleState.IDLE: frozenset(
        {
            ScanLifecycleState.DISCOVERED,
            ScanLifecycleState.CAPABILITIES_LOADED,
            ScanLifecycleState.ERROR,
        }
    ),
    ScanLifecycleState.DISCOVERED: frozenset(
        {
            ScanLifecycleState.CAPABILITIES_LOADED,
            ScanLifecycleState.ERROR,
        }
    ),
    ScanLifecycleState.CAPABILITIES_LOADED: frozenset(
        {
            ScanLifecycleState.JOB_CREATED,
            ScanLifecycleState.ERROR,
        }
    ),
    ScanLifecycleState.JOB_CREATED: frozenset(
        {
            ScanLifecycleState.POLLING,
            ScanLifecycleState.RETRIEVING,
            ScanLifecycleState.COMPLETED,
            ScanLifecycleState.ERROR,
            ScanLifecycleState.CANCELLED,
        }
    ),
    ScanLifecycleState.POLLING: frozenset(
        {
            ScanLifecycleState.RETRIEVING,
            ScanLifecycleState.ERROR,
            ScanLifecycleState.CANCELLED,
        }
    ),
    ScanLifecycleState.RETRIEVING: frozenset(
        {
            ScanLifecycleState.COMPLETED,
            ScanLifecycleState.ERROR,
            ScanLifecycleState.CANCELLED,
        }
    ),
}


class ScanLifecycleStateViolation(Exception):
    """Raised when ``strict=True`` and a transition is not allowed."""

    def __init__(self, from_state: ScanLifecycleState, to_state: ScanLifecycleState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"invalid scan lifecycle transition: {from_state.value} -> {to_state.value}")


class ScanLifecycle:
    """Tracks one ScanAvailable-driven chain from idle through a terminal state."""

    def __init__(self, *, strict: bool = False) -> None:
        self._strict = strict
        self._state = ScanLifecycleState.IDLE
        self._path: list[ScanLifecycleState] = [ScanLifecycleState.IDLE]
        self._violations: list[str] = []
        self._job_id: str | None = None

    @property
    def state(self) -> ScanLifecycleState:
        """Current lifecycle state."""
        return self._state

    @property
    def job_id(self) -> str | None:
        """Job id set when entering ``JobCreated``."""
        return self._job_id

    @property
    def path(self) -> tuple[ScanLifecycleState, ...]:
        """Ordered states visited (including repeats only on successful transition)."""
        return tuple(self._path)

    @property
    def violations(self) -> tuple[str, ...]:
        """Recorded invalid transition attempts (also logged)."""
        return tuple(self._violations)

    def is_terminal(self) -> bool:
        """Return True when the chain has reached a terminal state."""
        return self._state in TERMINAL_STATES

    def transition(self, to_state: ScanLifecycleState, *, job_id: str | None = None) -> None:
        """Move to ``to_state`` if allowed; log or raise on violation."""
        if self._state in TERMINAL_STATES:
            self._record_violation(self._state, to_state, reason="transition from terminal state")
            return
        allowed = _ALLOWED.get(self._state, frozenset())
        if to_state not in allowed:
            self._record_violation(self._state, to_state)
            return
        if job_id is not None:
            self._job_id = job_id
        self._state = to_state
        self._path.append(to_state)

    def mark_discovered(self) -> None:
        """Scanner XAddr is known for this chain (eventing registration path)."""
        self.transition(ScanLifecycleState.DISCOVERED)

    def mark_capabilities_loaded(self) -> None:
        """GetScannerElements (or tolerant continue) finished; ticket path may proceed."""
        if self._state == ScanLifecycleState.IDLE:
            self.transition(ScanLifecycleState.DISCOVERED)
        self.transition(ScanLifecycleState.CAPABILITIES_LOADED)

    def mark_job_created(self, job_id: str) -> None:
        """CreateScanJob succeeded with a job id."""
        self.transition(ScanLifecycleState.JOB_CREATED, job_id=job_id)

    def mark_polling(self) -> None:
        """Enter GetJobStatus polling loop."""
        self.transition(ScanLifecycleState.POLLING)

    def mark_retrieving(self) -> None:
        """Begin pull RetrieveImage (or idle wait after push-only handoff)."""
        self.transition(ScanLifecycleState.RETRIEVING)

    def mark_completed(self) -> None:
        """Chain finished successfully (image saved, push handoff, or benign skip)."""
        self.transition(ScanLifecycleState.COMPLETED)

    def mark_error(self) -> None:
        """Chain ended with SOAP/transport/validation failure."""
        self.transition(ScanLifecycleState.ERROR)

    def mark_cancelled(self) -> None:
        """CancelJob was issued (WIA §7.5 cleanup path)."""
        self.transition(ScanLifecycleState.CANCELLED)

    def enrich_result(self, result: dict[str, str | None]) -> dict[str, str | None]:
        """Add lifecycle fields for logging and tests."""
        out = dict(result)
        out["lifecycle_state"] = self._state.value
        out["lifecycle_path"] = " -> ".join(s.value for s in self._path)
        if self._job_id is not None:
            out["lifecycle_job_id"] = self._job_id
        if self._violations:
            out["lifecycle_state_violations"] = "; ".join(self._violations)
        return out

    def _record_violation(
        self,
        from_state: ScanLifecycleState,
        to_state: ScanLifecycleState,
        *,
        reason: str | None = None,
    ) -> None:
        msg = (
            f"{reason}: {from_state.value} -> {to_state.value}"
            if reason
            else f"{from_state.value} -> {to_state.value}"
        )
        self._violations.append(msg)
        log.warning(
            "Scan lifecycle state violation",
            extra={
                "lifecycle_from": from_state.value,
                "lifecycle_to": to_state.value,
                "lifecycle_job_id": self._job_id,
                "reason": reason,
            },
        )
        if self._strict:
            raise ScanLifecycleStateViolation(from_state, to_state)

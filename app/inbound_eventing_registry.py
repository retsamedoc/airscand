"""In-memory subscription state for inbound WS-Eventing (local subscription manager)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.soap.parsers.eventing import parse_iso8601_duration_to_seconds
from app.soap.parsers.inbound_eventing import _format_iso8601_duration_from_seconds


@dataclass
class _InboundSubscription:
    """Lease record for one inbound subscription id."""

    expires_at: float
    expires_granted_str: str


class InboundEventingRegistry:
    """Thread-safe map of subscription id → lease metadata for inbound manager ops."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, _InboundSubscription] = {}

    def reset_for_testing(self) -> None:
        """Clear all subscriptions (tests only)."""
        with self._lock:
            self._subs.clear()

    def create(self, identifier: str, granted_seconds: float, granted_expires_str: str) -> None:
        """Register a new subscription after a successful inbound ``Subscribe``."""
        now = time.time()
        with self._lock:
            self._subs[identifier] = _InboundSubscription(
                expires_at=now + float(granted_seconds),
                expires_granted_str=granted_expires_str,
            )

    def _get_live(self, identifier: str) -> _InboundSubscription | None:
        rec = self._subs.get(identifier)
        if rec is None:
            return None
        if time.time() > rec.expires_at:
            return None
        return rec

    def renew(
        self,
        identifier: str,
        *,
        requested_expires_raw: str | None,
        max_grant_seconds: float,
    ) -> str | None:
        """Extend lease; return new ``wse:Expires`` string or None if not renewable."""
        try:
            if requested_expires_raw and requested_expires_raw.strip():
                req_sec = parse_iso8601_duration_to_seconds(requested_expires_raw.strip())
            else:
                req_sec = parse_iso8601_duration_to_seconds("PT1H")
        except ValueError:
            return None
        grant = min(max(req_sec, 1.0), max(1.0, max_grant_seconds))
        granted_str = _format_iso8601_duration_from_seconds(grant)
        now = time.time()
        with self._lock:
            rec = self._subs.get(identifier)
            if rec is None or now > rec.expires_at:
                return None
            rec.expires_at = now + grant
            rec.expires_granted_str = granted_str
        return granted_str

    def get_status_expires(self, identifier: str) -> str | None:
        """Return remaining lease as ``xs:duration`` without mutating stored expiry deadline."""
        with self._lock:
            rec = self._subs.get(identifier)
            if rec is None:
                return None
            now = time.time()
            if now > rec.expires_at:
                return None
            remaining = max(0.0, rec.expires_at - now)
        return _format_iso8601_duration_from_seconds(remaining)

    def unsubscribe(self, identifier: str) -> bool:
        """Remove subscription; return True only if it existed and was not already expired."""
        now = time.time()
        with self._lock:
            rec = self._subs.pop(identifier, None)
            if rec is None:
                return False
            if now > rec.expires_at:
                return False
        return True


_REGISTRY = InboundEventingRegistry()


def inbound_eventing_registry() -> InboundEventingRegistry:
    """Return the process-wide inbound eventing subscription registry."""
    return _REGISTRY

"""In-memory subscription state for inbound WS-Eventing (subscription manager role)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

__all__ = [
    "InboundSubscription",
    "InboundSubscriptionEndDue",
    "InboundSubscriptionRegistry",
    "get_inbound_subscription_registry",
    "reset_inbound_subscription_registry",
]


@dataclass
class InboundSubscription:
    """Granted lease and addressing for one inbound subscription."""

    identifier: str
    granted_expires: str
    expires_at_monotonic: float
    manager_address: str
    notify_to_address: str
    subscription_end_to_url: str
    subscription_end_reference_parameters_xml: str | None


@dataclass(frozen=True)
class InboundSubscriptionEndDue:
    """One queued ``SubscriptionEnd`` POST to the subscriber's ``EndTo`` (or ``NotifyTo``)."""

    manager_address: str
    identifier: str
    subscription_end_to_url: str
    subscription_end_reference_parameters_xml: str | None


class InboundSubscriptionRegistry:
    """Thread-safe registry keyed by subscription identifier (``wsman:Identifier`` value)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, InboundSubscription] = {}
        self._pending_subscription_ends: list[InboundSubscriptionEndDue] = []

    def reset(self) -> None:
        """Drop all subscriptions (for tests)."""
        with self._lock:
            self._subs.clear()
            self._pending_subscription_ends.clear()

    def _append_subscription_end_locked(self, sub: InboundSubscription) -> None:
        self._pending_subscription_ends.append(
            InboundSubscriptionEndDue(
                manager_address=sub.manager_address,
                identifier=sub.identifier,
                subscription_end_to_url=sub.subscription_end_to_url,
                subscription_end_reference_parameters_xml=sub.subscription_end_reference_parameters_xml,
            )
        )

    def drain_pending_subscription_ends(self) -> list[InboundSubscriptionEndDue]:
        """Atomically take queued ``SubscriptionEnd`` deliveries (typically HTTP POST next)."""
        with self._lock:
            out = list(self._pending_subscription_ends)
            self._pending_subscription_ends.clear()
            return out

    def sweep_expired_leases(self) -> None:
        """Remove all expired subscriptions and enqueue ``SubscriptionEnd`` for each."""
        with self._lock:
            now = time.monotonic()
            expired_ids = [sid for sid, s in self._subs.items() if now >= s.expires_at_monotonic]
            for sid in expired_ids:
                sub = self._subs.pop(sid, None)
                if sub is not None:
                    self._append_subscription_end_locked(sub)

    def create(
        self,
        *,
        manager_address: str,
        granted_expires: str,
        grant_seconds: float,
        notify_to_address: str,
        subscription_end_to_url: str,
        subscription_end_reference_parameters_xml: str | None = None,
    ) -> InboundSubscription:
        """Allocate a new subscription id and store the granted lease."""
        identifier = f"urn:uuid:{uuid.uuid4()}"
        deadline = time.monotonic() + float(grant_seconds)
        sub = InboundSubscription(
            identifier=identifier,
            granted_expires=granted_expires,
            expires_at_monotonic=deadline,
            manager_address=manager_address,
            notify_to_address=notify_to_address,
            subscription_end_to_url=subscription_end_to_url,
            subscription_end_reference_parameters_xml=subscription_end_reference_parameters_xml,
        )
        with self._lock:
            self._subs[identifier] = sub
        return sub

    def renew(
        self,
        *,
        identifier: str,
        manager_address: str,
        granted_expires: str,
        grant_seconds: float,
    ) -> InboundSubscription | None:
        """Extend lease; return None if unknown, wrong manager, or already expired."""
        with self._lock:
            sub = self._subs.get(identifier)
            if sub is None:
                return None
            if sub.manager_address != manager_address:
                return None
            if time.monotonic() >= sub.expires_at_monotonic:
                del self._subs[identifier]
                self._append_subscription_end_locked(sub)
                return None
            sub.expires_at_monotonic = time.monotonic() + float(grant_seconds)
            sub.granted_expires = granted_expires
            return sub

    def get_status(self, identifier: str, manager_address: str) -> InboundSubscription | None:
        """Return active subscription without changing lease timestamps."""
        with self._lock:
            sub = self._subs.get(identifier)
            if sub is None:
                return None
            if sub.manager_address != manager_address:
                return None
            if time.monotonic() >= sub.expires_at_monotonic:
                del self._subs[identifier]
                self._append_subscription_end_locked(sub)
                return None
            return sub

    def unsubscribe(self, identifier: str, manager_address: str) -> bool:
        """Remove subscription; return False if missing or manager mismatch."""
        with self._lock:
            sub = self._subs.get(identifier)
            if sub is None or sub.manager_address != manager_address:
                return False
            if time.monotonic() >= sub.expires_at_monotonic:
                del self._subs[identifier]
                self._append_subscription_end_locked(sub)
                return False
            del self._subs[identifier]
            return True


_registry: InboundSubscriptionRegistry | None = None


def get_inbound_subscription_registry() -> InboundSubscriptionRegistry:
    """Return process-wide registry (lazily created)."""
    global _registry
    if _registry is None:
        _registry = InboundSubscriptionRegistry()
    return _registry


def reset_inbound_subscription_registry() -> None:
    """Reset the process-wide registry (tests)."""
    global _registry
    _registry = None

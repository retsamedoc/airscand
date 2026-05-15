"""In-memory subscription state for inbound WS-Eventing (subscription manager role)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

__all__ = [
    "InboundSubscription",
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


class InboundSubscriptionRegistry:
    """Thread-safe registry keyed by subscription identifier (``wsman:Identifier`` value)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, InboundSubscription] = {}

    def reset(self) -> None:
        """Drop all subscriptions (for tests)."""
        with self._lock:
            self._subs.clear()

    def create(
        self,
        *,
        manager_address: str,
        granted_expires: str,
        grant_seconds: float,
    ) -> InboundSubscription:
        """Allocate a new subscription id and store the granted lease."""
        identifier = f"urn:uuid:{uuid.uuid4()}"
        deadline = time.monotonic() + float(grant_seconds)
        sub = InboundSubscription(
            identifier=identifier,
            granted_expires=granted_expires,
            expires_at_monotonic=deadline,
            manager_address=manager_address,
        )
        with self._lock:
            self._subs[identifier] = sub
        return sub

    def _pop_if_expired_locked(self, sub: InboundSubscription) -> bool:
        if time.monotonic() < sub.expires_at_monotonic:
            return False
        self._subs.pop(sub.identifier, None)
        return True

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
            if self._pop_if_expired_locked(sub):
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
            if self._pop_if_expired_locked(sub):
                return None
            return self._subs.get(identifier)

    def unsubscribe(self, identifier: str, manager_address: str) -> bool:
        """Remove subscription; return False if missing or manager mismatch."""
        with self._lock:
            sub = self._subs.get(identifier)
            if sub is None or sub.manager_address != manager_address:
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

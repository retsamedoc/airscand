"""Tests for WS-Discovery XAddr rotation during scan-chain transport failures."""

from __future__ import annotations

import asyncio
from errno import ECONNREFUSED

from aiohttp import ClientConnectorError

from app.scanner_xaddr_failover import (
    ScannerXAddrRotator,
    normalize_scanner_xaddr_candidates,
)

_BAD = "http://192.168.1.99:80/WSD/DEVICE"
_GOOD = "http://192.168.1.60:80/WSD/DEVICE"
_ALT = "http://192.168.1.70:80/WSD/DEVICE"


def test_normalize_dedupes_and_prefers_active() -> None:
    """Active XAddr is first when missing from the candidate list."""
    result = normalize_scanner_xaddr_candidates(
        _GOOD,
        [_BAD, _BAD, _ALT],
    )
    assert result == [_GOOD, _BAD, _ALT]


def test_rotator_advance_on_timeout_only() -> None:
    """Transport timeouts advance to the next ordered candidate."""
    rotator = ScannerXAddrRotator.from_scanner_xaddr(_BAD, [_BAD, _GOOD])
    assert rotator.scanner_xaddr == _BAD
    assert rotator.failover_count == 0

    advanced = rotator.advance(
        asyncio.TimeoutError(), context="scan_chain", operation="ValidateScanTicket"
    )

    assert advanced is True
    assert rotator.scanner_xaddr == _GOOD
    assert rotator.failover_count == 1


def test_rotator_exhausted_returns_false() -> None:
    """Non-transport errors and exhausted lists do not advance."""
    rotator = ScannerXAddrRotator.from_scanner_xaddr(_GOOD, [_GOOD])

    assert (
        rotator.advance(ValueError("bad"), context="scan_chain", operation="CreateScanJob") is False
    )
    assert rotator.scanner_xaddr == _GOOD
    assert rotator.failover_count == 0

    rotator_multi = ScannerXAddrRotator.from_scanner_xaddr(_BAD, [_BAD, _GOOD])
    rotator_multi.advance(
        asyncio.TimeoutError(), context="scan_chain", operation="ValidateScanTicket"
    )
    assert rotator_multi.scanner_xaddr == _GOOD

    assert (
        rotator_multi.advance(
            ClientConnectorError(connection_key=None, os_error=OSError(ECONNREFUSED, "refused")),
            context="scan_chain",
            operation="CreateScanJob",
        )
        is False
    )
    assert rotator_multi.scanner_xaddr == _GOOD
    assert rotator_multi.failover_count == 1

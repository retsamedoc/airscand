"""Tests for post-retrieve Idle coordination."""

from __future__ import annotations

import asyncio

import pytest

from app import scanner_status_coordination as ssc


@pytest.mark.asyncio
async def test_await_scanner_idle_signals_on_notify_idle() -> None:
    """notify_scanner_state(Idle) unblocks await_scanner_idle_after_retrieve."""

    async def fire_idle() -> None:
        await asyncio.sleep(0.01)
        ssc.notify_scanner_state("Idle")

    ssc.begin_retrieve_idle_wait()
    try:
        asyncio.create_task(fire_idle())
        ok = await ssc.await_scanner_idle_after_retrieve(2.0)
        assert ok is True
    finally:
        ssc.end_retrieve_idle_wait()


@pytest.mark.asyncio
async def test_await_scanner_idle_times_out_when_no_idle() -> None:
    """Without Idle notification, wait returns False."""
    ssc.begin_retrieve_idle_wait()
    try:
        ok = await ssc.await_scanner_idle_after_retrieve(0.05)
        assert ok is False
    finally:
        ssc.end_retrieve_idle_wait()


@pytest.mark.asyncio
async def test_processing_does_not_complete_wait_until_idle() -> None:
    """Only Idle completes the wait; Processing alone times out."""
    ssc.begin_retrieve_idle_wait()
    try:
        ssc.notify_scanner_state("Processing")
        ok = await ssc.await_scanner_idle_after_retrieve(0.05)
        assert ok is False
    finally:
        ssc.end_retrieve_idle_wait()

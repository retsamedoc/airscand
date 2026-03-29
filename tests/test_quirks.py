"""Tests for scanner vendor profile registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.quirks import PROFILE_EPSON_WF_3640, PROFILE_GENERIC, get_profile

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


def test_get_profile_known_keys() -> None:
    """Registered keys resolve to stable profile objects."""
    assert get_profile("generic") is PROFILE_GENERIC
    assert get_profile("epson_wf_3640") is PROFILE_EPSON_WF_3640
    assert get_profile("EPSON_WF_3640") is PROFILE_EPSON_WF_3640
    assert get_profile("epson") is PROFILE_EPSON_WF_3640


def test_epson_wf3640_disables_get_job_status_poll() -> None:
    """WF-3640 does not support GetJobStatus; profile skips that polling step."""
    assert PROFILE_GENERIC.poll_get_job_status_before_retrieve is True
    assert PROFILE_EPSON_WF_3640.poll_get_job_status_before_retrieve is False


def test_profile_retrieve_image_timeouts() -> None:
    """Generic uses short RetrieveImage read timeout; WF-3640 allows longer MTOM transfer."""
    assert PROFILE_GENERIC.retrieve_image_timeout_sec == 5.0
    assert PROFILE_EPSON_WF_3640.retrieve_image_timeout_sec == 60.0


def test_get_profile_empty_string_falls_back_to_generic() -> None:
    """Blank config should not crash lookup."""
    assert get_profile("") is PROFILE_GENERIC
    assert get_profile("   ") is PROFILE_GENERIC


def test_get_profile_unknown_warns_and_uses_generic(caplog: LogCaptureFixture) -> None:
    """Unknown profile keys log a warning and use the generic profile."""
    caplog.set_level(logging.WARNING)
    p = get_profile("no_such_vendor_xyz")
    assert p is PROFILE_GENERIC
    assert any("Unknown scanner profile" in r.message for r in caplog.records)


def test_config_scanner_profile_env(monkeypatch: MonkeyPatch) -> None:
    """WSD_SCANNER_PROFILE is exposed on Config."""
    monkeypatch.setenv("WSD_SCANNER_PROFILE", "generic")
    from app.config import Config

    cfg = Config()
    assert cfg.scanner_profile == "generic"


def test_epson_module_reexports_profile() -> None:
    """``app.quirks.epson`` exposes the same WF-3640 profile object as ``app.quirks``."""
    from app.quirks.epson import PROFILE_EPSON_WF_3640 as ep

    assert ep.key == "epson_wf_3640"


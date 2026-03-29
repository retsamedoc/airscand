"""Epson scanner profiles and vendor-wide defaults.

Put **model-specific** quirks here (e.g. WorkForce WF-3640). If we discover settings that
apply to **most Epson devices**, define shared helpers or a base ``ScannerProfile`` here
and compose per-model profiles from them.

See ``docs/protocol/vendor_quirks.md`` for field behavior notes.
"""

from __future__ import annotations

from . import ScannerProfile

__all__ = ["PROFILE_EPSON_WF_3640"]

# WorkForce WF-3640 (tested): GetJobStatus not usable on the pull scan path; use a longer
# RetrieveImage read timeout for chunked MTOM bodies.
PROFILE_EPSON_WF_3640 = ScannerProfile(
    key="epson_wf_3640",
    description="Epson WorkForce WF-3640 (tested); GetJobStatus not supported.",
    poll_get_job_status_before_retrieve=False,
    retrieve_image_timeout_sec=60.0,
)

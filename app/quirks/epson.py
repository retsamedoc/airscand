"""Epson-specific scanner profiles.

``PROFILE_EPSON_WF_3640`` disables ``GetJobStatus`` polling (see ``vendor_quirks.md``).
Further SOAP/timing tweaks may be added here; see ``docs/protocol/vendor_quirks.md``.
"""

from . import PROFILE_EPSON_WF_3640

__all__ = ["PROFILE_EPSON_WF_3640"]

"""ING-4: the text-only sidebar rows must render from stored detected_* fields,
never re-parse the channel name at render.

Re-parsing disagrees with the stored value whenever detected_region was filled
from the provider category or a sibling channel (not the name), so the sidebar
would drop a [REGION] tag that every other view shows.  _fmt_channel_name gains
a stored mode (used by the Favorites / Queue / Recommended DTO callers) that
reads the ingestion-computed fields and does not parse; the raw-name Alerts
caller keeps the parse fallback.
"""
from unittest.mock import patch

from metatv.gui.sidebar import base as _base
from metatv.gui.sidebar.base import _fmt_channel_name


def test_stored_mode_uses_detected_region_without_parsing():
    """A region that came from the category (not the name) is shown, and
    parse_channel_name is NOT called."""
    with patch.object(
        _base, "parse_channel_name",
        side_effect=AssertionError("parse_channel_name called in stored mode — render-parse"),
    ):
        out = _fmt_channel_name(
            "Peliculas",                 # name carries no region token
            detected_title="Peliculas",
            detected_region="ES",        # filled from category/sibling at ingestion
            detected_quality="HD",
            detected_year="2024",
        )
    assert out == "Peliculas · 2024 [ES] [HD]", out
    assert "[ES]" in out  # the tag re-parsing would have dropped


def test_stored_mode_falls_back_to_name_when_title_empty():
    """detected_title='' (stored but empty) still enters stored mode and shows name."""
    with patch.object(_base, "parse_channel_name", side_effect=AssertionError("parsed")):
        out = _fmt_channel_name("Some Channel", detected_title="", detected_region="", detected_quality="")
    assert out == "Some Channel", out


def test_raw_name_caller_still_parses():
    """With no detected_* fields (the Alerts raw-name caller), parsing still runs."""
    out = _fmt_channel_name("UK: Sky Sports HD")
    assert "Sky Sports" in out
    assert "[HD]" in out

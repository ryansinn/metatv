"""B10-2 tail: _SimilarSection._make_row reads stored detected_* fields, no render-time parse.

`ChannelVersion` now carries `detected_title`/`detected_year` (populated at fetch from the
stored ingestion fields), so the Similar-Titles row renders from them instead of re-parsing
the raw channel name — per the CLAUDE.md ingestion-only rule.
"""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from metatv.gui.details_versions import ChannelVersion


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _texts(widget) -> list[str]:
    return [w.text() for w in widget.findChildren((QLabel, QPushButton))]


def test_make_row_uses_detected_title_and_year_not_raw_name(qapp):
    from metatv.gui.details_similar import _SimilarSection

    cfg = MagicMock()
    cfg.category_name_overrides = {}
    section = _SimilarSection(cfg)
    section._channel_ids = ["c1"]   # _make_row indexes into this for the preview action

    v = ChannelVersion(
        channel_id="c1",
        name="EN | GARBAGE RAW NAME (1999) [Multi-Sub]",  # would parse to the wrong title
        in_queue=False,
        detected_prefix=None,                              # skip the prefix-chip path
        detected_title="Real Clean Show",
        detected_year="2024",
        media_type="movie",
    )
    row = section._make_row(v)
    texts = _texts(row)

    # Title button shows the STORED detected_title, not the parsed raw name.
    assert "Real Clean Show" in texts, f"expected stored title; got {texts}"
    assert not any("GARBAGE" in t for t in texts), f"raw name leaked: {texts}"
    # Stored year is used.
    assert any("2024" in t for t in texts), f"expected stored year 2024; got {texts}"
    assert not any("1999" in t for t in texts), f"parsed year leaked: {texts}"


def test_channel_version_carries_stored_title_year_fields():
    """The DTO must expose detected_title / detected_year (default None)."""
    v = ChannelVersion(channel_id="c", name="n", in_queue=False)
    assert v.detected_title is None and v.detected_year is None
    v2 = ChannelVersion(channel_id="c", name="n", in_queue=False,
                        detected_title="T", detected_year="2020")
    assert v2.detected_title == "T" and v2.detected_year == "2020"

"""Similar Titles rows: the tooltip leads with the whole title, actions second.

The row elides a long title to fit its column, so the tooltip is the one place
the whole title can be read. It used to carry only the verbs ("Click: preview
in lightbox …" / "Play: <title>"), so a long title was cut off on the row and
buried behind the verb in the tooltip (owner, 2026-09-07: "the titles are cut
off"). Now line 1 is the full title and line 2 the actions.
"""
from __future__ import annotations

import pytest

LONG = "A Deliberately Very Long Similar Title That No Row Column Could Ever Show Whole"


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _row(qapp):
    from metatv.core.config import Config
    from metatv.gui.details_similar import _SimilarSection
    from metatv.gui.details_versions import ChannelVersion

    section = _SimilarSection(Config())
    version = ChannelVersion(channel_id="c1", name=LONG, in_queue=False)
    section._channel_ids = [version.channel_id]
    return section, section._make_row(version)


def _tooltips(row_w) -> list[str]:
    from PyQt6.QtWidgets import QPushButton

    return [b.toolTip() for b in row_w.findChildren(QPushButton)]


def test_the_title_button_tooltip_leads_with_the_whole_title(qapp):
    from tests.conftest import destroy_widget

    section, row = _row(qapp)
    try:
        tips = [t for t in _tooltips(row) if "preview in lightbox" in t]
        assert tips, "the title button's tooltip should still name its actions"
        lines = tips[0].split("\n")
        assert lines[0] == LONG, lines
        assert "Click: preview in lightbox" in lines[1]
        assert "Right-click: open in details pane" in lines[1]
    finally:
        destroy_widget(row, section)


def test_the_play_button_tooltip_leads_with_the_whole_title(qapp):
    from tests.conftest import destroy_widget

    section, row = _row(qapp)
    try:
        tips = [t for t in _tooltips(row) if t.split("\n")[-1] == "Play"]
        assert tips, "the play button's tooltip should end with its verb on its own line"
        assert tips[0].split("\n")[0] == LONG
    finally:
        destroy_widget(row, section)

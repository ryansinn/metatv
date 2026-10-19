"""An episode with no overview of its own shows the series' under its own name.

Owner (2026-10-19): head it "Series overview" rather than "Overview", and
remember whether it is collapsed separately from a real overview's state.
"""

from metatv.gui.details_sections import _PlotSection


def test_the_series_fallback_has_its_own_title_and_fold(qapp, qtbot):
    section = _PlotSection()
    qtbot.addWidget(section)
    saved = ["overview_series"]          # the user folded the series fallback

    section.restore_collapse_state(saved)
    assert not section._header.is_collapsed(), "a real overview stays open"

    section.rekey("overview_series", "Series overview", saved)
    assert section._header.title() == "Series overview"
    assert section._header.is_collapsed(), "the fallback remembers its own fold"

    section.rekey("overview", "Overview", saved)
    assert section._header.title() == "Overview"
    assert not section._header.is_collapsed()

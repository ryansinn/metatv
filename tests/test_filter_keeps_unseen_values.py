"""A value the filter panel isn't showing keeps its saved state.

The panel's counts are scoped by Global Exclusions and active sources, so a
value can be absent from the panel for a while. ``save_state`` used to write
only the ticked values it could see; an absent value dropped out of
``filter_included_*`` while staying in ``filter_known_*``, and when it came
back the opt-out restore read it as deliberately unticked — a Language or
Platform filter the user never set, shown as a chip on every search.

Owner's real state (2026-10-19): 11 languages, 49 regions, 2 platforms, both
dub languages and 464 genres stuck off this way, 285 of the genres present on
the active source.
"""

from __future__ import annotations

from tests.conftest import drain_chunked_build
from tests.test_filter_panel_persistence import _build_panel, _make_config, _make_stats


def _panel(qapp, qtbot, cfg):
    panel = _build_panel(qapp, cfg)
    qtbot.addWidget(panel)
    return panel


def _show(panel, langs: dict) -> None:
    panel.update_data(_make_stats(lang_groups=langs))
    drain_chunked_build(panel._update_handle)


def test_a_value_absent_at_save_is_still_included_when_it_returns(qapp, qtbot):
    cfg = _make_config()
    cfg.filter_known_languages = ["EN", "FR", "DE"]

    # German titles are globally excluded right now: the panel never shows DE.
    panel = _panel(qapp, qtbot, cfg)
    _show(panel, {"EN": 100, "FR": 50})
    panel.save_state()

    # The exclusion is lifted; a fresh launch counts German again.
    relaunched = _panel(qapp, qtbot, cfg)
    _show(relaunched, {"EN": 100, "FR": 50, "DE": 30})

    assert set(relaunched._lang_sec.get_selected_keys()) == {"EN", "FR", "DE"}
    assert "language" not in (relaunched.get_filter_state()["tag_includes"] or {})


def test_a_value_the_user_unticked_stays_unticked_while_absent(qapp, qtbot):
    cfg = _make_config(filter_included_languages=["EN", "FR"])
    cfg.filter_known_languages = ["EN", "FR", "DE"]  # DE deliberately off

    panel = _panel(qapp, qtbot, cfg)
    _show(panel, {"EN": 100, "FR": 50})  # DE absent
    panel.save_state()

    relaunched = _panel(qapp, qtbot, cfg)
    _show(relaunched, {"EN": 100, "FR": 50, "DE": 30})
    assert "DE" not in relaunched._lang_sec.get_selected_keys()


def test_all_button_clears_a_value_stuck_off_while_absent(qapp, qtbot):
    """The way out for state the old save already damaged."""
    cfg = _make_config(filter_included_languages=["EN", "FR"])
    cfg.filter_known_languages = ["EN", "FR", "DE"]

    panel = _panel(qapp, qtbot, cfg)
    _show(panel, {"EN": 100, "FR": 50})
    panel.select_all_sections()

    relaunched = _panel(qapp, qtbot, cfg)
    _show(relaunched, {"EN": 100, "FR": 50, "DE": 30})
    assert set(relaunched._lang_sec.get_selected_keys()) == {"EN", "FR", "DE"}

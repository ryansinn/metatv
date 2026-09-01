"""The channel list must not blank and reload itself seconds after launch.

Owner, 2026-09-01: *"the results load, then something else happens, and the
results are refreshed all within a matter of seconds without any interaction
with the app"* — and, separately, *"I can confirm the reload changed nothing"*.

Their log shows it exactly:

    00:31:14.253  Loading 1 channels (filtered from 785,551 total)
    00:31:14.255  set_channels: 1 rows, gen=2
    00:31:31.910  Initialized filter stats … 544,827 occurrences
    00:31:32.015  Filter changed, reloading channels...
    00:31:32.016  set_channels: 0 rows, gen=3          <- list goes EMPTY
    00:31:33.517  set_channels: 1 rows, gen=4          <- same row again

``FilterPanel.update_data`` runs when the background facet-stats query lands,
~18s after launch, and emitted ``filter_changed`` unconditionally on that first
call. The emit exists for a real reason — the first ``load_channels`` runs while
the facet sections are still empty, so a restored facet filter could not be
applied — but when the restore constrains nothing, the reload returns identical
rows and the user watches the list blank for a second for no reason.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _Sec:
    """Stands in for a facet section, with only what the predicate reads."""

    def __init__(self, all_selected=True, keys=("a", "b"),
                 untagged_row=False, untagged_on=True):
        self._all = all_selected
        self._keys = list(keys)
        self._untagged_row = untagged_row
        self._untagged_on = untagged_on

    def is_all_selected(self):
        return self._all

    def get_all_keys(self):
        return list(self._keys)

    def has_untagged_row(self):
        return self._untagged_row

    def untagged_included(self):
        return self._untagged_on


def _panel(sections: dict):
    from metatv.gui.filter_panel import FilterPanel
    p = FilterPanel.__new__(FilterPanel)
    p._facet_sections = lambda: sections
    return p


class TestReloadOnlyWhenItWouldChangeSomething:

    def test_an_unconstrained_restore_does_not_reload(self, qapp):
        """The reported bug: every facet fully selected, so the reload is a no-op."""
        p = _panel({f"f{i}": _Sec(all_selected=True) for i in range(9)})
        assert p._restore_constrains_the_query() is False

    def test_a_deselected_value_does_reload(self, qapp):
        """Non-degeneracy: a real saved filter must still be applied."""
        secs = {f"f{i}": _Sec(all_selected=True) for i in range(9)}
        secs["f3"] = _Sec(all_selected=False, keys=("a", "b"))
        p = _panel(secs)
        assert p._restore_constrains_the_query() is True

    def test_a_hidden_untagged_footer_does_reload(self, qapp):
        """Hiding "Untagged" constrains the query without deselecting a value.

        Checking only ``is_all_selected`` would miss this and silently show
        rows the user had chosen to hide.
        """
        secs = {f"f{i}": _Sec(all_selected=True) for i in range(9)}
        secs["f5"] = _Sec(all_selected=True, untagged_row=True, untagged_on=False)
        p = _panel(secs)
        assert p._restore_constrains_the_query() is True

    def test_an_empty_section_is_not_a_constraint(self, qapp):
        """No items means no data for that facet, not "exclude everything"."""
        secs = {f"f{i}": _Sec(all_selected=True) for i in range(9)}
        secs["f2"] = _Sec(all_selected=False, keys=())
        p = _panel(secs)
        assert p._restore_constrains_the_query() is False

    def test_a_broken_section_reloads_rather_than_guessing(self, qapp):
        """Unsure → reload. A wasted query is cheap; ignoring a saved filter is not."""
        class _Boom:
            def is_all_selected(self):
                raise RuntimeError("wrapped C++ object deleted")

        secs = {f"f{i}": _Sec(all_selected=True) for i in range(9)}
        secs["f1"] = _Boom()
        p = _panel(secs)
        assert p._restore_constrains_the_query() is True

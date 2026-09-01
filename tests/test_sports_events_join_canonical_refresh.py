"""Sports and Events must re-read after a source refresh.

Owner, 2026-09-01: clicked "MLB 04 | Royals x Blue Jays" in Sports and watched
Mariners x Red Sox. Nothing played the wrong stream — the refresh had renamed
that row IN PLACE (same provider, same stream id 1037143), the database was
correct, and only the view was stale.

``_refresh_provider_dependent_views`` is the one place every corpus-derived view
re-reads from. It listed discover, preferences, recipe, missing_tmdb,
reconnect_engaged and epg — and NOT sports or events, the two views built
entirely from the channel corpus. Exactly the enumeration the rule exists to
prevent: an entry nobody remembered to add.

Three models were wrong before this one, and each was disproved with data
rather than argued away:

* *stream ids are recycled within a provider* — no: the two ``MLB 04`` rows
  belong to DIFFERENT providers (TREX Shared and Shark), and the id is
  ``provider_id + "_" + stream_id``, so they cannot collide.
* *a disabled source is leaking rows* — no: ``get_hidden_provider_ids()``
  returns TREX and the scope excludes it correctly.
* *the refresh fails to prune departed rows* — not this bug: the row was
  renamed, not orphaned.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class TestBothViewsAreInTheCanonicalRefresh:

    def _host(self, **views):
        from metatv.gui.main_window_providers import _ProviderMixin
        h = _ProviderMixin.__new__(_ProviderMixin)
        for name in ("load_providers", "load_favorites", "load_history",
                     "_refresh_queue_section", "_refresh_recommended_section",
                     "load_channels", "initialize_filter_stats"):
            setattr(h, name, MagicMock())
        for k, v in views.items():
            setattr(h, k, v)
        return h

    def test_sports_view_is_reloaded(self, qapp):
        from metatv.gui.main_window_providers import _ProviderMixin
        sports = MagicMock()
        h = self._host(sports_view=sports)
        _ProviderMixin._refresh_provider_dependent_views(h)
        sports.reload.assert_called_once(), (
            "Sports was left out of the canonical refresh — it keeps showing "
            "fixture names the refresh has already replaced")

    def test_events_view_is_reloaded(self, qapp):
        from metatv.gui.main_window_providers import _ProviderMixin
        events = MagicMock()
        h = self._host(events_view=events)
        _ProviderMixin._refresh_provider_dependent_views(h)
        events.reload.assert_called_once()

    def test_a_window_without_them_still_refreshes(self, qapp):
        """They are built lazily; the refresh must not require them."""
        from metatv.gui.main_window_providers import _ProviderMixin
        h = self._host()
        _ProviderMixin._refresh_provider_dependent_views(h)   # must not raise
        h.load_channels.assert_called_once()


class TestReloadOnlyCostsSomethingWhenVisible:

    def test_a_hidden_sports_view_does_not_re_query(self, qapp):
        """A hidden view re-reads on its next on_activate; querying now is waste."""
        from metatv.gui.sports_view import SportsView
        v = SportsView.__new__(SportsView)
        v.isVisible = lambda: False
        v.on_activate = MagicMock()
        v._taxonomy_requested = True
        SportsView.reload(v)
        v.on_activate.assert_not_called()
        assert v._taxonomy_requested is False, (
            "the taxonomy must still be re-read on the next activation — a "
            "refresh can add or remove a whole sport")

    def test_a_visible_sports_view_re_reads(self, qapp):
        from metatv.gui.sports_view import SportsView
        v = SportsView.__new__(SportsView)
        v.isVisible = lambda: True
        v.on_activate = MagicMock()
        v._taxonomy_requested = True
        SportsView.reload(v)
        v.on_activate.assert_called_once()

    def test_a_hidden_events_view_does_not_re_query(self, qapp):
        from metatv.gui.events_view import EventsView
        v = EventsView.__new__(EventsView)
        v.isVisible = lambda: False
        v._reload = MagicMock()
        EventsView.reload(v)
        v._reload.assert_not_called()

    def test_a_visible_events_view_re_reads(self, qapp):
        from metatv.gui.events_view import EventsView
        v = EventsView.__new__(EventsView)
        v.isVisible = lambda: True
        v._reload = MagicMock()
        EventsView.reload(v)
        v._reload.assert_called_once()

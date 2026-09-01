"""Three UX faults the owner hit in one sitting, 2026-09-01.

1. **A single search result could not be clicked.** The details pane is driven
   by ``currentChanged``, which does not fire when the clicked row is already
   current, and ``on_channel_selection_changed`` returns early on
   ``_last_shown_channel_id`` besides. With ONE result the list auto-selects it,
   so the only row on screen is already current and there is no other row to
   click away to: *"I can't single click Ghostbusters in the search results to
   get it to populate the details panel"*.

2. **Closing a part-watched film left the pane showing Play, not Resume.** The
   position is stored during playback, but the pane was rendered before the
   watch existed: *"I was half way through watching the movie, closed the movie,
   the details panel should show resume"*.

3. Both together meant recovering the item required finding it on another
   surface (History, Watch Queue) to force a fresh render.
"""

from __future__ import annotations

from unittest.mock import MagicMock



class TestAnExplicitClickAlwaysShowsDetails:

    def _host(self, shown=None):
        from metatv.gui.main_window_channels import _ChannelListMixin
        h = _ChannelListMixin.__new__(_ChannelListMixin)
        h._last_shown_channel_id = shown
        h.show_channel_details_by_id = MagicMock()
        return h

    def _index(self, channel_id, kind="channel"):
        from PyQt6.QtCore import Qt
        from metatv.gui.channel_list_model import ROW_KIND_ROLE
        idx = MagicMock()
        idx.data.side_effect = lambda role: {
            ROW_KIND_ROLE: kind, Qt.ItemDataRole.UserRole: channel_id,
        }.get(role)
        return idx

    def test_clicking_the_already_selected_row_repopulates(self):
        """The reported bug: one result, already current, click does nothing."""
        from metatv.gui.main_window_channels import _ChannelListMixin
        h = self._host(shown="ch-1")
        _ChannelListMixin._on_channel_list_clicked(h, self._index("ch-1"))
        h.show_channel_details_by_id.assert_called_once_with("ch-1"), (
            "an explicit click on the current row must still open it — the "
            "de-dupe guard exists to skip redundant renders, not the user")

    def test_clicking_a_different_row_still_works(self):
        from metatv.gui.main_window_channels import _ChannelListMixin
        h = self._host(shown="ch-1")
        _ChannelListMixin._on_channel_list_clicked(h, self._index("ch-2"))
        h.show_channel_details_by_id.assert_called_once_with("ch-2")

    def test_a_row_with_no_channel_id_is_ignored(self):
        from metatv.gui.main_window_channels import _ChannelListMixin
        h = self._host()
        _ChannelListMixin._on_channel_list_clicked(h, self._index(None))
        assert h.show_channel_details_by_id.call_count == 0


class TestClosingPlaybackOffersResume:

    def _host(self, playing, shown):
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = _StreamingMixin.__new__(_StreamingMixin)
        h._playing_channels = dict(playing)
        h._last_shown_channel_id = shown
        h.show_channel_details_by_id = MagicMock()
        return h

    def test_the_pane_re_reads_the_title_that_just_stopped(self):
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = self._host({"k1": "ch-9"}, "ch-9")
        _StreamingMixin._refresh_details_after_playback_stopped(h, "k1")
        h.show_channel_details_by_id.assert_called_once_with("ch-9"), (
            "a part-watched film still offers only Play after closing mpv")

    def test_a_null_key_resolves_the_shared_window(self):
        """The health probe can report a null key for the shared instance."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = self._host({"__shared__": "ch-9"}, "ch-9")
        _StreamingMixin._refresh_details_after_playback_stopped(h, None)
        h.show_channel_details_by_id.assert_called_once_with("ch-9")

    def test_it_does_not_fight_the_user_for_the_pane(self):
        """If they have since clicked something else, leave it alone."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = self._host({"k1": "ch-9"}, "ch-OTHER")
        _StreamingMixin._refresh_details_after_playback_stopped(h, "k1")
        assert h.show_channel_details_by_id.call_count == 0

    def test_it_fires_once_not_on_every_idle_tick(self):
        """The idle poll ticks every 2s; re-rendering each time would thrash."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = self._host({"k1": "ch-9"}, "ch-9")
        _StreamingMixin._refresh_details_after_playback_stopped(h, "k1")
        _StreamingMixin._refresh_details_after_playback_stopped(h, "k1")
        assert h.show_channel_details_by_id.call_count == 1

    def test_nothing_playing_is_a_no_op(self):
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = self._host({}, "ch-1")
        _StreamingMixin._refresh_details_after_playback_stopped(h, "k1")
        assert h.show_channel_details_by_id.call_count == 0

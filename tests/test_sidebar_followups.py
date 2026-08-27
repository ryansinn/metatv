"""Two reported faults, both in code this session wrote.

**A section closed groups the user had opened.** Three separate reports, one
mechanism: the fold pass. It has been removed rather than repaired — see
:mod:`metatv.gui.sidebar.section_cap` — so what survives here is the narrowest
of the three, which is a contract in its own right whatever the mechanism:
toggling one group must not move another. Owner: "in main the EPG just
collapsed on it's own while clicking on the Stream Monitoring subheader."

**No way to reach the series.** Double-clicking a watched episode in History
opens the series browser, so the only route to it is a gesture that should have
played the episode. "Browse the series" now sits with the other series-scoped
actions — the owner spotted that grouping already half-present: "like and
dislike options ... apply to the series, not the episode, so maybe the browse
series menu option should be bundled near them."
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class TestReachingTheSeries:

    def test_browse_series_is_registered_and_series_only(self):
        from metatv.gui.channel_menu import ACTIONS

        action = ACTIONS["browse_series"]
        assert action.label == "Browse the series"

        class _Ctx:
            is_single = True
            channel_found = True
            is_hidden = False
            media_type = "series"

        ctx = _Ctx()
        assert action.applies(ctx)
        ctx.media_type = "movie"
        assert not action.applies(ctx), "it offered to browse a film"
        ctx.media_type = "series"
        ctx.is_hidden = True
        assert not action.applies(ctx)

    def test_it_sits_with_the_other_series_actions(self):
        """Beside monitor_series, not up among the play actions: both concern
        the SERIES while everything above concerns this one episode."""
        from metatv.gui.channel_menu import SURFACE_LAYOUTS

        for surface, layout in SURFACE_LAYOUTS.items():
            if "browse_series" not in layout:
                continue
            i, j = layout.index("browse_series"), layout.index("monitor_series")
            assert j == i + 1, f"{surface}: not adjacent to monitor_series"
            # ...and after the judgment pair, which is title-level too.
            if "like" in layout:
                assert layout.index("like") < i, surface

    def test_every_surface_offering_it_can_handle_it(self):
        """A listed action with no handler is a menu entry that does nothing."""
        import inspect

        from metatv.gui import main_window_channels
        from metatv.gui.channel_menu import SURFACE_LAYOUTS

        src = inspect.getsource(main_window_channels)
        offering = [s for s, l in SURFACE_LAYOUTS.items() if "browse_series" in l]
        assert offering, "nothing offers it"
        assert '"browse_series": lambda' in src, (
            "browse_series is in a layout but has no entry in the handler map"
        )

    def test_the_host_implements_what_the_handler_calls(self):
        from metatv.gui.main_window import MainWindow

        assert hasattr(MainWindow, "browse_series_by_id")


class TestOpeningOneGroupDoesNotCloseAnother:
    """Folding answers "there is less space", not "there is more content".

    Toggling a group changes the content height, which re-ran the fold pass,
    which closed a different group to make room — so clicking Stream Monitoring
    silently collapsed EPG. Owner: "the EPG just collapsed on it's own while
    clicking on the Stream Monitor subheader."

    Content that outgrows its section is what the scroll area is for. Only a
    RESIZE folds anything now; a content change re-derives the cap and stops.
    """

    def _section(self, qapp, tmp_path):
        from datetime import datetime, timedelta

        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        from metatv.core.config import Config
        from metatv.gui.sidebar.alerts import WatchAlertsSection, _Airing

        now = datetime(2026, 8, 26, 12, 0, 0)

        class _Cfg:
            def __init__(self, base):
                self.__dict__["_b"] = base
                self.get_vod_watch_alerts = lambda: []
                self.get_monitored_series = lambda: [{
                    "cid": "s0", "channel_id": "s0", "title": "President Curtis",
                    "display_title": "President Curtis", "unseen": 15,
                    "unseen_new": 15, "language": "EN", "region": "US",
                    "source": "TREX"}]
                self.get_vod_rule_unviewed_count = lambda _c: 0
                self.get_rules_with_new_matches_count = lambda: 0
                self.get_unviewed_vod_match_count = lambda: 0

            def __getattr__(self, n):
                if n == "alerts_show_idle_items":
                    return True
                return getattr(self.__dict__["_b"], n)

        sec = WatchAlertsSection(_Cfg(Config(config_dir=tmp_path)), db=None)
        host = QWidget()
        host.setFixedSize(300, 420)          # too small for all of it
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(sec)
        host.show()
        groups = {
            f"g{i}": {"title": f"Programme {i}", "upcoming": [],
                      "live": [_Airing(5, "5m", f"CH{i}", f"c{i}",
                                       now + timedelta(minutes=5),
                                       now - timedelta(minutes=25), "", "US")]}
            for i in range(12)
        }
        sec._populate_rows({"empty_reason": "", "live_groups": groups,
                            "upcoming_only": {}})
        sec.refresh_vod_rules()
        for _ in range(6):
            qapp.processEvents()
        return sec, host

    def test_toggling_one_group_leaves_the_others_alone(self, qapp, tmp_path):
        sec, host = self._section(qapp, tmp_path)
        try:
            before = sec._epg_collapsed
            sec._toggle_stream_monitoring()
            # Long enough for anything DEBOUNCED to fire if it were scheduled
            # — otherwise a mutation that re-schedules a pass passes unnoticed,
            # because the timer never gets to run inside a tight event loop.
            deadline = time.monotonic() + (sec.CAP_DEBOUNCE_MS / 1000) * 4
            while time.monotonic() < deadline:
                qapp.processEvents()
                time.sleep(0.005)
            assert sec._epg_collapsed == before, (
                "opening Stream Monitoring collapsed EPG"
            )
        finally:
            host.deleteLater()
            qapp.processEvents()

    def test_measuring_the_content_does_not_recurse(self, qapp, tmp_path):
        """The cap measures content, which re-runs the row budget, which calls
        back into the cap. Guarded — without it the two bounce until the stack
        runs out, which is a crash rather than a wrong pixel."""
        sec, host = self._section(qapp, tmp_path)
        try:
            for _ in range(5):
                sec._apply_content_cap()      # would RecursionError unguarded
            sec.reapply_row_budget()
            assert sec.maximumHeight() > 0
        finally:
            host.deleteLater()
            qapp.processEvents()

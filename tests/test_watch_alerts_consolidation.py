"""Behavioral tests for the Watch Alerts consolidation.

Covers the paths that would break if the consolidation regressed:

- ``_series_display_entries`` ordering: new-episode series pinned first, each
  group A–Z, and rendered by the CLEANED ``display_title`` (never the raw name).
- ``WatchAlertsSection.refresh_vod_rules`` renders keyword rules, then a
  ``──── Series ────`` divider, then series rows — new ones coloured green.
- Series collapse toggle hides the series rows (divider stays).
- ``ManageVodAlertsDialog`` populates BOTH sections from config and its per-series
  Stop removes the entry + emits ``changed``.
- Config migration silently strips a stale ``new_episodes`` sidebar id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeConfig:
    """In-memory Config stub with the monitored-series + vod-rule helpers.

    Carries ``expand_icon`` / ``collapse_icon`` (the divider arrow) so the real
    ``refresh_vod_rules`` render path runs unmodified.
    """

    expand_icon = ">"
    collapse_icon = "v"

    def __init__(self):
        self.monitored_series = []
        self.vod_watch_alerts = []

    def save(self):
        pass

    # ── monitored series ──────────────────────────────────────────────────
    def add_monitored_series(self, entry: dict) -> None:
        self.monitored_series = list(self.monitored_series) + [entry]

    def get_monitored_series(self) -> list:
        return list(self.monitored_series)

    def remove_monitored_series(self, cid: str) -> None:
        self.monitored_series = [
            e for e in self.monitored_series if e.get("series_channel_id") != cid
        ]

    def is_series_monitored(self, cid: str) -> bool:
        return any(e.get("series_channel_id") == cid for e in self.monitored_series)

    # ── vod watch alerts ──────────────────────────────────────────────────
    def add_vod_watch_alert(self, rule: dict) -> None:
        self.vod_watch_alerts = list(self.vod_watch_alerts) + [rule]

    def get_vod_watch_alerts(self) -> list:
        return list(self.vod_watch_alerts)

    def remove_vod_watch_alert(self, rule_created: str) -> None:
        self.vod_watch_alerts = [
            r for r in self.vod_watch_alerts if r.get("created") != rule_created
        ]

    def get_rules_with_new_matches_count(self) -> int:
        return 0

    def get_unviewed_vod_match_count(self) -> int:
        return 0

    def get_vod_rule_unviewed_count(self, _created: str) -> int:
        return 0


def _series(cid: str, title: str, unseen: int, display: str | None = None) -> dict:
    return {
        "series_channel_id": cid,
        "source_id": "s",
        "provider_id": "p1",
        "title": title,
        "display_title": display,
        "unseen_new": unseen,
        "baseline_episode_count": 10,
        "last_checked": None,
    }


def _make_section(config):
    """A WatchAlertsSection stub exercising only the Movies & Series render path."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection.__new__(WatchAlertsSection)
    section.config = config
    from tests.conftest import wire_watch_alerts_group_state
    wire_watch_alerts_group_state(section)
    section._series_collapsed = False
    section._vod_list = QListWidget()
    section._update_vod_toggle_label = MagicMock()
    section.update_new_match_badge = MagicMock()
    return section


def _row_labels(row):
    from PyQt6.QtWidgets import QLabel
    # QLabel AND QPushButton — see the note in test_vod_watch_alerts.
    from PyQt6.QtWidgets import QPushButton

    return row.findChildren((QLabel, QPushButton))


# ===========================================================================
# Part 1: _series_display_entries — ordering, pinning, cleaned title
# ===========================================================================

class TestSeriesDisplayEntries:

    def test_new_pinned_first_each_group_alpha_by_cleaned_title(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("z", "EN - Zebra (2001)", 0, "Zebra"))
        cfg.add_monitored_series(_series("a", "EN - Apple (2010)", 2, "Apple"))
        cfg.add_monitored_series(_series("m", "FR - Mango", 5, "Mango"))
        cfg.add_monitored_series(_series("b", "Bravo Show", 0, "Bravo"))

        section = _make_section(cfg)
        got = [(s["title"], s["unseen"]) for s in section._series_display_entries()]

        # New (unseen>0) pinned first A–Z, then idle A–Z — all by CLEANED title.
        assert got == [
            ("Apple", 2), ("Mango", 5),   # new, A–Z
            ("Bravo", 0), ("Zebra", 0),   # idle, A–Z
        ], got

    def test_display_title_used_not_raw_name(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(
            _series("rm", "EN - Rick And Morty (2013)", 3, "Rick and Morty")
        )
        section = _make_section(cfg)
        titles = [s["title"] for s in section._series_display_entries()]
        assert titles == ["Rick and Morty"], titles

    def test_falls_back_to_raw_title_when_no_display_title(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("x", "Raw Only Title", 0, None))
        section = _make_section(cfg)
        assert section._series_display_entries()[0]["title"] == "Raw Only Title"


# ===========================================================================
# Part 2: refresh_vod_rules renders the Movies & Series list
# ===========================================================================

class TestRefreshMoviesSeries:

    def _kinds(self, section):
        from metatv.gui.sidebar.alerts import _ROLE_KIND
        lst = section._vod_list
        return [lst.item(i).data(_ROLE_KIND) for i in range(lst.count())]

    def test_series_only_renders_divider_plus_rows(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        cfg.add_monitored_series(_series("b", "Bravo", 0, "Bravo"))
        section = _make_section(cfg)

        section.refresh_vod_rules()

        # divider + 2 series rows (no keyword rules)
        assert self._kinds(section) == ["heading", "series", "series"]

    def test_new_series_pinned_and_coloured_green(self, qapp):
        import metatv.gui.theme as _theme
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("z", "Zebra", 0, "Zebra"))
        cfg.add_monitored_series(_series("a", "Apple", 3, "Apple"))
        section = _make_section(cfg)

        section.refresh_vod_rules()
        lst = section._vod_list

        # item 0 = divider, item 1 = first (pinned) series row
        first_row = lst.itemWidget(lst.item(1))
        labels = _row_labels(first_row)
        texts = [w.text() for w in labels]
        assert any("Apple" in t for t in texts), texts          # pinned new one first
        # "+3", not "+3 eps": the count is a narrow CHIP now, and the group it
        # sits under is called Series, so the unit is already said. The tooltip
        # still spells it out.
        assert any("+3" in t for t in texts), texts             # non-colour cue (count)
        # The chip is FILLED with COLOR_OK rather than tinted text — colour
        # paired with the count, never colour alone.
        count_chip = labels[-1]
        sheet = count_chip.styleSheet()
        assert _theme.COLOR_OK in sheet, sheet
        assert "background" in sheet, "the new count should be a filled pill"

        # idle series row (item 2) shows no count at all.
        #
        # This used to assert the last label's sheet equalled
        # VOD_ALERT_COUNT_IDLE, which passed for the wrong reason: an idle row
        # has never HAD a count chip, so the label being measured was the
        # title — and VOD_ALERT_NAME and VOD_ALERT_COUNT_IDLE were the same
        # string ("color: <COLOR_TEXT>;"), so an assertion about the count
        # was satisfied by the name. Both roles are gone; assert the absence
        # the test is named for instead.
        idle_row = lst.itemWidget(lst.item(2))
        idle_texts = [w.text() for w in _row_labels(idle_row)]
        assert any("Zebra" in t for t in idle_texts), idle_texts
        assert not any(t.startswith("+") for t in idle_texts), idle_texts
        assert len(_row_labels(idle_row)) < len(labels), (
            "an idle row should carry fewer widgets than one with a count"
        )

    def test_rules_render_before_series_divider(self, qapp):
        cfg = _FakeConfig()
        cfg.add_vod_watch_alert({
            "text": "Dune", "match_type": "movie", "created": _now_iso(),
            "alerted_ids": [], "viewed_ids": [],
        })
        cfg.add_monitored_series(_series("a", "Apple", 0, "Apple"))
        section = _make_section(cfg)

        section.refresh_vod_rules()

        # With BOTH groups present, the keyword group gets a "Watching for" label
        # above its rules, mirroring the Series divider below.
        assert self._kinds(section) == [
            "heading", "rule", "heading", "series",
        ]

    def test_no_keyword_divider_when_only_rules(self, qapp):
        cfg = _FakeConfig()
        cfg.add_vod_watch_alert({
            "text": "Dune", "match_type": "movie", "created": _now_iso(),
            "alerted_ids": [], "viewed_ids": [],
        })
        section = _make_section(cfg)

        section.refresh_vod_rules()

        # A single group needs no label (the sub-section toggle already names it).
        assert self._kinds(section) == ["rule"]

    def test_no_rules_no_series_hides_subsection(self, qapp):
        cfg = _FakeConfig()
        section = _make_section(cfg)
        section.refresh_vod_rules()
        assert section._vod_list.count() == 0
        # The 'Movies & Series' wrapper was dissolved; the LIST is what
        # hides when there is nothing to show.
        assert section._vod_list.isHidden()

    def test_series_collapsed_hides_rows_keeps_divider(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        cfg.add_monitored_series(_series("b", "Bravo", 0, "Bravo"))
        section = _make_section(cfg)
        section._series_collapsed = True

        section.refresh_vod_rules()

        # Only the divider row survives when the series block is collapsed.
        assert self._kinds(section) == ["heading"]


# ===========================================================================
# Part 3: click routing on the Movies & Series list
# ===========================================================================

class TestSeriesClickRouting:

    def test_series_row_click_emits_series_clicked(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.refresh_vod_rules()
        section.seriesClicked = MagicMock()

        lst = section._vod_list
        # item 1 is the series row (item 0 is the divider)
        section._on_vod_item_clicked(lst.item(1))
        section.seriesClicked.emit.assert_called_once_with("a")

    def test_divider_click_toggles_series_collapse(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.refresh_vod_rules()
        assert section._series_collapsed is False

        # The heading's WIDGET owns the click now, not the item. #463 made
        # every heading a NoItemFlags item carrying a GroupHeading, precisely so
        # item flags stop doing double duty as "is content" and "is clickable" —
        # which is what left one divider inert while its identical twin toggled.
        #
        # Asserted as "the heading is wired, and the handler works" rather than
        # by emitting: this section is a __new__'d skeleton, and a signal
        # connected to a bound method of a QObject whose C++ super-init never
        # ran REGISTERS but never delivers. Emitting here proves nothing and
        # fails for a reason unrelated to the behaviour.
        from metatv.gui.sidebar.base import GroupHeading

        heading = section._vod_list.itemWidget(section._vod_list.item(0))
        assert isinstance(heading, GroupHeading)
        assert heading.receivers(heading.clicked) == 1, (
            "the Series heading is not wired to anything — the inert-divider bug"
        )
        section._toggle_series_group()
        assert section._series_collapsed is True
        section._toggle_series_group()
        assert section._series_collapsed is False


# ===========================================================================
# Part 4: ManageVodAlertsDialog — both sections + per-series Stop
# ===========================================================================

class TestManageDialogSeriesSection:

    def _labels_text(self, dlg) -> list[str]:
        from PyQt6.QtWidgets import QLabel
        return [w.text() for w in dlg._scroll_content.findChildren(QLabel)]

    def test_lists_keyword_rules_and_series_with_cleaned_titles(self, qapp):
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog
        cfg = _FakeConfig()
        cfg.add_vod_watch_alert({
            "text": "Dune", "match_type": "movie", "created": _now_iso(),
            "alerted_ids": [], "viewed_ids": [],
        })
        cfg.add_monitored_series(
            _series("rm", "EN - Rick And Morty (2013)", 3, "Rick and Morty")
        )

        dlg = ManageVodAlertsDialog(cfg)
        texts = self._labels_text(dlg)

        assert any("Movies & Series — keyword rules" in t for t in texts), texts
        assert any("Series — new-episode alerts" in t for t in texts), texts
        assert any("Dune" in t for t in texts), texts
        # Cleaned title, NOT the raw "EN - Rick And Morty (2013)".
        assert any("Rick and Morty" in t for t in texts), texts
        assert not any("EN - Rick And Morty" in t for t in texts), texts

    def test_stop_is_recoverable_until_close_then_removes_and_emits_changed(self, qapp):
        """Stop only marks the series pending — the actual removal + `changed` land on close.

        Recoverable-remove (mirror-not-cage): matches the keyword-rule Remove
        behavior — Stop flips the row to pending, the series survives until the
        dialog closes, and Undo before then restores it fully.
        """
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 0, "Apple"))
        cfg.add_monitored_series(_series("b", "Bravo", 0, "Bravo"))

        dlg = ManageVodAlertsDialog(cfg)
        changed: list[bool] = []
        dlg.changed.connect(lambda: changed.append(True))

        dlg._stop_series("a")

        assert not changed, "changed must NOT fire yet — Stop only marks pending"
        assert cfg.is_series_monitored("a"), "series must survive until the dialog closes"
        assert "a" in dlg._pending_remove_series

        dlg.reject()  # Close/Esc/window-X all route through reject()

        assert not cfg.is_series_monitored("a"), "stopped series must be removed on close"
        assert cfg.is_series_monitored("b"), "other series must remain"
        assert changed, "changed must emit so the host refreshes dependent views"

    def test_stop_series_undo_restores_it(self, qapp):
        """Undo before close discards the pending-stop — the series keeps monitoring."""
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 0, "Apple"))

        dlg = ManageVodAlertsDialog(cfg)
        dlg._stop_series("a")
        assert "a" in dlg._pending_remove_series

        dlg._undo_series("a")
        assert "a" not in dlg._pending_remove_series

        dlg.reject()  # finalize — nothing pending, so nothing is removed
        assert cfg.is_series_monitored("a"), "undone series must survive finalize"

    def test_empty_state_shows_both_section_hints(self, qapp):
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog
        dlg = ManageVodAlertsDialog(_FakeConfig())
        texts = self._labels_text(dlg)
        assert any("No keyword rules yet" in t for t in texts), texts
        assert any("No monitored series yet" in t for t in texts), texts


# ===========================================================================
# Part 4b: the REAL section constructs (header Manage button + EPG sub-header)
# and renders series through the non-stub path.
# ===========================================================================

class TestRealSectionConstruction:

    def test_constructs_and_renders_series(self, qapp, tmp_path):
        from metatv.core.config import Config
        from metatv.core.database import Database
        from metatv.gui.sidebar.alerts import WatchAlertsSection, _ROLE_KIND

        db = Database("sqlite:///:memory:")
        db.create_tables()
        cfg, _ = Config.load()  # isolated to a tmp HOME by the autouse fixture
        sec = WatchAlertsSection(cfg, db)
        try:
            # The Manage affordance must exist. Icon-only now (the three-slider
            # "tune" glyph): as a text button it did not fit on the group-heading
            # line it shares, truncating "Movies & Series (6) · 2 new". The
            # tooltip carries the word.
            assert sec._manage_btn.toolTip(), "Manage needs a tooltip — it is icon-only"
            assert not sec._manage_btn.icon().isNull(), "Manage has no glyph"

            # Empty: header-only, no Movies & Series rows.
            sec.refresh_vod_rules()
            assert sec._vod_list.count() == 0

            # A new-episode series + an idle one → divider + 2 rows, new one pinned.
            cfg.monitored_series = [
                _series("a", "EN - Rick And Morty (2013)", 3, "Rick and Morty"),
                _series("b", "EN - The Wire (2002)", 0, "The Wire"),
            ]
            sec.refresh_vod_rules()
            kinds = [
                sec._vod_list.item(i).data(_ROLE_KIND)
                for i in range(sec._vod_list.count())
            ]
            assert kinds == ["heading", "series", "series"]
            first = sec._vod_list.itemWidget(sec._vod_list.item(1))
            assert any("Rick and Morty" in w.text() for w in _row_labels(first))
        finally:
            ex = getattr(sec, "_executor", None)
            if ex is not None:
                ex.shutdown(wait=False)
            db.close()


# ===========================================================================
# Part 5: config migration tolerates a stale "new_episodes" sidebar id
# ===========================================================================

class TestSidebarMigration:

    def test_inject_new_sections_strips_stale_new_episodes(self, tmp_path):
        """"new_episodes" (folded into Watch Alerts) is stripped; "alerts" is kept.

        Note: "sources" is ALSO retired from these lists as of Wave 6 (Sources
        moved out of the sidebar section stack into the status strip + Sources
        manager view) — see TestSourcesSidebarRetirement below for that migration.
        """
        from metatv.core.config import Config
        cfg = Config()
        cfg.sidebar_sections = ["new_episodes", "alerts"]
        cfg.sidebar_visible_sections = ["new_episodes", "alerts"]

        cfg._inject_new_sections()

        assert "new_episodes" not in cfg.sidebar_sections
        assert "new_episodes" not in cfg.sidebar_visible_sections
        assert "alerts" in cfg.sidebar_sections

"""The Sources editor's Analytics tab (WIP-1 step 2), on the real editor.

Seeds three sources on a file-backed Database, opens the editor on the
Analytics tab and asserts what is ON SCREEN: the only-here counts, a Shared
bar per source and type whose PAINTED fill matches the share, a disabled or
expired source greyed AND labelled, the redundancy hint, and "Browse them"
handing the only-here channel ids to the host. The editor runs its queries
synchronously here (no MainWindow seam); the app passes ``_run_query``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.gui.progress_paint import ProgressBar
from tests.conftest import destroy_widget


@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed(db):
    """TREX: 20 films. Shark (expired) carries 19 of them — all but film1 — so 95%;
    ProSat carries 5 (film2-film6) plus one of its own. film1 is only on TREX."""
    from metatv.core.database import ChannelDB, ProviderDB
    with db.session_scope() as s:
        s.add(ProviderDB(id="trex", name="TREX", type="xtream", url="http://t", username="u",
                         password="p", is_active=True,
                         account_exp_date=datetime.now() + timedelta(days=27, hours=1)))
        s.add(ProviderDB(id="shark", name="Shark", type="xtream", url="http://s", username="u",
                         password="p", is_active=False,
                         account_exp_date=datetime.now() - timedelta(days=3)))
        s.add(ProviderDB(id="prosat", name="ProSat", type="xtream", url="http://p", username="u",
                         password="p", is_active=True))

        def ch(pid, key):
            s.add(ChannelDB(id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id=pid,
                            name=key, media_type="movie", content_key=key))
        for i in range(20):
            ch("trex", f"film{i}")
        for i in [0, *range(2, 21)]:      # film20 is Shark's own
            ch("shark", f"film{i}")
        for i in range(2, 7):
            ch("prosat", f"film{i}")
        ch("prosat", "prosat-only")


def _analytics(qapp, db, provider_id="trex"):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(db)
    ed.resize(700, 900)
    ed.show()
    ed._tabs.setCurrentWidget(ed._analytics_scroll)
    ed.load_provider(provider_id)
    qapp.processEvents()
    return ed


def _texts(widget) -> list[str]:
    return [lbl.text() for lbl in widget.findChildren(QLabel) if lbl.isVisible()]


def _painted_fraction(bar: ProgressBar) -> float:
    """Where the fill colour stops along the bar's middle row, as a fraction."""
    img = bar.grab().toImage()
    y, fill = img.height() // 2, img.pixelColor(1, img.height() // 2)
    end = next((x for x in range(1, img.width()) if img.pixelColor(x, y) != fill), img.width())
    return end / img.width()


def test_only_here_counts_and_browse_hands_over_the_ids(qapp, file_db):
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        tab = ed._analytics_tab
        assert tab._only.title.text() == "Only on TREX"
        line = next(t for t in _texts(tab._only) if "no other source has these" in t)
        assert "<b>1</b> films" in line, line          # film1 is only on TREX
        got = []
        ed.browse_ids_requested.connect(lambda label, ids: got.append((label, ids)))
        browse = next(b for b in tab._only.findChildren(QPushButton) if b.text() == "Browse them")
        browse.click()
        assert got and got[0][0] == "Only on TREX" and len(got[0][1]) == 1
    finally:
        destroy_widget(ed)


def test_shared_bars_paint_the_share_and_grey_an_expired_source(qapp, file_db):
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        shared = ed._analytics_tab._shared
        texts = _texts(shared)
        assert "Shark (expired) · films" in texts, "a greyed row must also SAY why"
        assert "19 of 20" in texts and "5 of 20" in texts
        bars = shared.findChildren(ProgressBar)
        fractions = sorted(round(_painted_fraction(b), 2) for b in bars)
        assert fractions[0] == pytest.approx(0.25, abs=0.04)   # ProSat 5 of 20
        assert fractions[-1] == pytest.approx(0.95, abs=0.04)  # Shark 19 of 20
        # A share has no "nearly over" state: 95% paints the accent, not the warning colour.
        from metatv.gui import theme as _theme
        from metatv.gui.token_color import to_qcolor
        top = max(bars, key=_painted_fraction).grab().toImage()
        assert top.pixelColor(1, top.height() // 2).name() == to_qcolor(_theme.COLOR_ACCENT).name()
        shark = next(lbl for lbl in shared.findChildren(QLabel) if lbl.text() == "Shark (expired) · films")
        prosat = next(lbl for lbl in shared.findChildren(QLabel) if lbl.text() == "ProSat · films")
        assert shark.palette().color(shark.foregroundRole()) != prosat.palette().color(prosat.foregroundRole())
    finally:
        destroy_widget(ed)


def test_redundancy_hint_at_ninety_five_percent(qapp, file_db):
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        assert any("Shark carries almost everything TREX does" in t
                   for t in _texts(ed._analytics_tab._shared))
    finally:
        destroy_widget(ed)


def test_catalogue_line_and_days_left(qapp, file_db):
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        cat = ed._analytics_tab._catalogue
        assert cat.subtitle.text() == "27 days left"
        assert any("<b>20</b> films" in t for t in _texts(cat))
    finally:
        destroy_widget(ed)


def test_a_new_unsaved_source_says_so(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    try:
        ed._tabs.setCurrentWidget(ed._analytics_scroll)
        ed.start_new_source()
        assert ed._analytics_tab._empty.isVisibleTo(ed._analytics_tab)
        assert not ed._analytics_tab._only.isVisibleTo(ed._analytics_tab)
    finally:
        destroy_widget(ed)


def test_switching_tabs_away_drops_in_flight_results(qapp, file_db):
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        before = {k: v[0] for k, v in ed._analytics_tab._tokens.items()}
        ed._tabs.setCurrentIndex(0)
        after = {k: v[0] for k, v in ed._analytics_tab._tokens.items()}
        assert all(after[k] > before[k] for k in before)
    finally:
        destroy_widget(ed)


def test_playback_section_reports_recorded_outcomes(qapp, file_db):
    _seed(file_db)
    from metatv.core.repositories import RepositoryFactory
    when = datetime(2026, 10, 20, 21, 0)
    with file_db.session_scope() as s:
        repo = RepositoryFactory(s).playback_events
        for outcome, ttp in [("started", 1200), ("started", 2400), ("refused", None), ("dropped", 1800)]:
            repo.record(provider_id="trex", channel_id="c", title="t", outcome=outcome,
                        started_at=when, time_to_picture_ms=ttp)
    ed = _analytics(qapp, file_db)
    try:
        texts = _texts(ed._analytics_tab._playback)
        assert "3 of 4 (75%)" in texts          # plays started (dropped counts as started)
        assert "1.8 s typical" in texts
        assert ed._analytics_tab._playback.subtitle.text().startswith("since ")
    finally:
        destroy_widget(ed)


def test_playback_section_with_nothing_recorded(qapp, file_db):
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        assert any("Nothing recorded yet" in t for t in _texts(ed._analytics_tab._playback))
    finally:
        destroy_widget(ed)


def test_sections_follow_the_approved_order(qapp, file_db):
    """Q2 order, with What you watch second: is the source worth keeping, answered first."""
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        tab = ed._analytics_tab
        order = sorted(tab._sections(), key=lambda sec: sec.mapTo(tab, sec.rect().topLeft()).y())
        assert [sec.title.text() for sec in order] == [
            "Only on TREX", "What you watch here", "Shared with your other sources", "Playback", "Connections",
            "Server addresses",
            "Catalogue & guide", "Unrecognized prefixes"]
    finally:
        destroy_widget(ed)


def _play(db, provider_id, key, plays, *, title=None, media="movie", region=None, last=None):
    """One channel on *provider_id* with a play history."""
    from metatv.core.database import ChannelDB
    with db.session_scope() as s:
        s.add(ChannelDB(id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id=provider_id,
                        name=title or key, detected_title=title, media_type=media, content_key=key,
                        detected_region=region, play_count=plays, last_played=last))


def test_what_you_watch_names_titles_plays_and_the_most_played(qapp, file_db):
    _seed(file_db)
    _play(file_db, "trex", "fut", 12, title="Futurama", media="series",
          last=datetime(2026, 10, 30, 9, 0))
    _play(file_db, "trex", "fut", 7, title="Futurama", media="series")   # a second row, same title
    _play(file_db, "trex", "ac", 5, title="Altered Carbon & Co", media="series")
    _play(file_db, "trex", "ib", 2, title="Innocent Blood")
    _play(file_db, "trex", "low", 1, title="Least")
    _play(file_db, "prosat", "other", 50, title="Not TREX")
    from metatv.core.repositories import RepositoryFactory
    with file_db.session_scope() as s:
        repo = RepositoryFactory(s).playback_events
        event = repo.record(provider_id="trex", channel_id="c", title="t", outcome="started",
                            started_at=datetime(2026, 10, 31, 9, 0))
        repo.update(event, seconds_watched=5400)
    ed = _analytics(qapp, file_db)
    try:
        viewing = ed._analytics_tab._viewing
        texts = _texts(viewing)
        assert "4 (2 films · 2 series)" in texts                 # titles, not rows
        assert "27" in texts                                     # plays, ProSat's excluded
        assert any(t.startswith("1.5 h since") for t in texts)
        most = next(t for t in texts if t.startswith("Most played"))
        assert most.index("Futurama (19)") < most.index("Altered Carbon &amp; Co (5)") \
            < most.index("Innocent Blood (2)")
        assert "Least" not in most                               # top three only
        assert viewing.subtitle.text().startswith("last played ")
    finally:
        destroy_widget(ed)


def test_what_you_watch_with_nothing_played(qapp, file_db):
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        assert "Nothing played from this source yet." in _texts(ed._analytics_tab._viewing)
    finally:
        destroy_widget(ed)


def test_region_bars_paint_each_regions_share(qapp, file_db):
    """TREX's seeded 20 films have no region; add 30 French and 10 German: FR 50%, DE ~17%."""
    _seed(file_db)
    for i in range(30):
        _play(file_db, "trex", f"fr{i}", 0, region="FR")
    for i in range(10):
        _play(file_db, "trex", f"de{i}", 0, region="DE")
    ed = _analytics(qapp, file_db)
    try:
        cat = ed._analytics_tab._catalogue
        texts = _texts(cat)
        assert "50%" in texts and "17%" in texts
        assert any("20 titles with no region" in t for t in texts)
        bars = [b for b in cat.findChildren(ProgressBar) if b.isVisible()]
        assert len(bars) == 2
        assert _painted_fraction(bars[0]) == pytest.approx(0.50, abs=0.04)
        assert _painted_fraction(bars[1]) == pytest.approx(1 / 6, abs=0.04)
    finally:
        destroy_widget(ed)

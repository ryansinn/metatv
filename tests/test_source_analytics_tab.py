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
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

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


def _analytics(qapp, db, provider_id="trex", width=700):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(db)
    ed.resize(width, 900)
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
        only = tab._tiles["only"]
        assert (only.figure.text(), only.caption.text()) == ("1", "titles only on TREX")  # film1
        got = []
        ed.browse_ids_requested.connect(lambda label, ids: got.append((label, ids)))
        browse = next(b for b in only.findChildren(QPushButton) if b.text() == "Browse them")
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
        assert "Shark (expired)" in texts, "a greyed row must also SAY why"
        assert "95%" in texts and "25%" in texts
        tips = [w.toolTip() for w in shared.findChildren(QWidget) if w.toolTip()]
        assert any("19 of this source's 20 films" in t for t in tips)
        bars = shared.findChildren(ProgressBar)
        assert all(b.width() <= 60 for b in bars), "short bars, not page-wide tracks"
        fractions = sorted(round(_painted_fraction(b), 2) for b in bars)
        assert fractions[0] == pytest.approx(0.25, abs=0.04)   # ProSat 5 of 20
        assert fractions[-1] == pytest.approx(0.95, abs=0.04)  # Shark 19 of 20
        # A share has no "nearly over" state: 95% paints the accent, not the warning colour.
        from metatv.gui import theme as _theme
        from metatv.gui.token_color import to_qcolor
        top = max(bars, key=_painted_fraction).grab().toImage()
        assert top.pixelColor(1, top.height() // 2).name() == to_qcolor(_theme.COLOR_ACCENT).name()
        shark = next(lbl for lbl in shared.findChildren(QLabel) if lbl.text() == "Shark (expired)")
        prosat = next(lbl for lbl in shared.findChildren(QLabel) if lbl.text() == "ProSat")
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


def test_catalogue_tiles_and_days_left(qapp, file_db):
    _seed(file_db)
    ed = _analytics(qapp, file_db)
    try:
        tiles = ed._analytics_tab._tiles
        assert (tiles["days"].figure.text(), tiles["days"].caption.text()) == ("27", "days left")
        assert (tiles["movie"].figure.text(), tiles["movie"].caption.text()) == ("20", "films")
        assert not tiles["live"].figure.text() or tiles["live"].figure.text() == "0"
    finally:
        destroy_widget(ed)


def test_a_new_unsaved_source_says_so(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    try:
        ed._tabs.setCurrentWidget(ed._analytics_scroll)
        ed.start_new_source()
        assert ed._analytics_tab._empty.isVisibleTo(ed._analytics_tab)
        assert not ed._analytics_tab._tiles_box.isVisibleTo(ed._analytics_tab)
        assert not ed._analytics_tab._viewing.isVisibleTo(ed._analytics_tab)
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
        started = ed._analytics_tab._tiles["started"]        # dropped counts as started
        assert (started.figure.text(), started.caption.text()) == ("75%", "of plays started (3 of 4)")
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


def _top_left(tab, widget):
    point = widget.mapTo(tab, widget.rect().topLeft())
    return point.x(), point.y()


def test_wide_cards_sit_in_two_columns_under_the_tiles(qapp, file_db):
    """Re-layout 2026-10-31 (Q13/Q14): tiles first; left column what the source
    carries, right column how it behaves; regions and prefixes full width below."""
    _seed(file_db)
    ed = _analytics(qapp, file_db, width=1300)
    try:
        tab = ed._analytics_tab
        left = [tab._viewing, tab._shared]
        right = [tab._playback, tab._connections, tab._addresses]
        tiles_bottom = tab._tiles_box.mapTo(tab, tab._tiles_box.rect().bottomLeft()).y()
        xs = {sec: _top_left(tab, sec)[0] for sec in left + right}
        assert len({xs[s] for s in left}) == 1 and len({xs[s] for s in right}) == 1
        assert xs[left[0]] < xs[right[0]]
        for column in (left, right):
            ys = [_top_left(tab, s)[1] for s in column]
            assert tiles_bottom < ys[0] and ys == sorted(ys)
        cards_bottom = max(s.mapTo(tab, s.rect().bottomLeft()).y() for s in left + right)
        assert cards_bottom < _top_left(tab, tab._catalogue)[1] < _top_left(tab, tab._prefixes)[1]
        assert tab._catalogue.width() > 2 * tab._viewing.width() - 40     # full width
    finally:
        destroy_widget(ed)


def test_narrow_cards_stack_and_regions_go_two_across(qapp, file_db):
    _seed(file_db)
    for i, code in enumerate(("FR", "DE", "IT", "ES", "PL")):
        _play(file_db, "trex", f"r{i}", 0, region=code)
    ed = _analytics(qapp, file_db, width=700)
    try:
        tab = ed._analytics_tab
        assert _top_left(tab, tab._viewing)[0] == _top_left(tab, tab._playback)[0]
        names = [w for w in tab._catalogue.findChildren(QLabel) if w.toolTip().startswith("Browse the")]
        rows = sorted({_top_left(tab, w)[1] for w in names})
        assert len(names) == 5 and len(rows) == 3                         # two across, not three
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
        assert any("<b>4</b> of the 4 titles you've played are on no other source" in t for t in texts)
        # Most played: one row per title, most first, each with its plays.
        rows = {lbl.text(): _top_left(viewing, lbl)[1] for lbl in viewing.findChildren(QLabel)
                if lbl.isVisible() and lbl.text() in ("Futurama", "Altered Carbon & Co", "Innocent Blood",
                                                      "Least")}
        assert rows["Futurama"] < rows["Altered Carbon & Co"] < rows["Innocent Blood"] < rows["Least"]
        assert "19 plays" in texts and "1 play" in texts
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


def test_clicking_a_region_browses_its_channels_on_this_source(qapp, file_db):
    """Q18: a region name is a link; it hands that region's channels to Search."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    _seed(file_db)
    for i in range(3):
        _play(file_db, "trex", f"fr{i}", 0, region="FR")
    _play(file_db, "prosat", "frx", 0, region="FR")                 # another source's: not handed over
    ed = _analytics(qapp, file_db, width=1300)
    try:
        got = []
        ed.browse_ids_requested.connect(lambda label, ids: got.append((label, ids)))
        link = next(w for w in ed._analytics_tab._catalogue.findChildren(QLabel)
                    if w.toolTip() == "Browse the 3 titles in France on this source")
        for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
            qapp.sendEvent(link, QMouseEvent(kind, QPointF(4, 4), QPointF(4, 4), Qt.MouseButton.LeftButton,
                                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        assert got and got[0][0] == "France on TREX" and len(got[0][1]) == 3
    finally:
        destroy_widget(ed)


def test_show_all_opens_every_region_in_place_and_folds_back(qapp, file_db):
    """The old "+ 203 more regions" could not be opened; Show all can."""
    from metatv.gui.source_analytics_tab import REGION_ROWS, REGIONS_ACROSS_WIDE
    codes = ["FR", "DE", "IT", "ES", "PL", "NL", "SE", "NO", "FI", "DK", "PT", "GR", "TR", "RO", "HU",
             "CZ", "SK", "BG"]
    _seed(file_db)
    for i, code in enumerate(codes):
        for j in range(len(codes) - i):                              # distinct counts, FR largest
            _play(file_db, "trex", f"{code}{j}", 0, region=code)
    ed = _analytics(qapp, file_db, width=1300)
    try:
        cat = ed._analytics_tab._catalogue

        def shown():
            return [w for w in cat.findChildren(QLabel) if w.toolTip().startswith("Browse the") and w.isVisible()]

        assert len(shown()) == REGION_ROWS * REGIONS_ACROSS_WIDE
        button = next(b for b in cat.findChildren(QPushButton) if "Show all (18)" in b.text())
        button.click()
        assert len(shown()) == len(codes) and button.text() == "Show fewer"
        button.click()
        assert len(shown()) == REGION_ROWS * REGIONS_ACROSS_WIDE
    finally:
        destroy_widget(ed)


def test_what_you_watch_counts_recent_episodes_and_favourites(qapp, file_db):
    from metatv.core.database import ChannelDB, EpisodeDB
    _seed(file_db)
    _play(file_db, "trex", "fut", 3, title="Futurama", media="series", last=datetime.utcnow())
    with file_db.session_scope() as s:
        fav = s.query(ChannelDB).filter_by(provider_id="trex", content_key="film3").first()
        fav.is_favorite = True
        for n in range(4):
            s.add(EpisodeDB(id=f"e{n}", season_id="x", series_id="s1" if n < 3 else "s2",
                            provider_id="trex", episode_id=f"e{n}", episode_num=n, season_num=1,
                            title=f"Ep {n}", play_count=1))
    ed = _analytics(qapp, file_db)
    try:
        texts = _texts(ed._analytics_tab._viewing)
        assert "1 titles" in texts                      # played in the last 30 days
        assert "4 across 2 series" in texts
        assert "Favourites here" in texts
    finally:
        destroy_widget(ed)


def test_clicking_a_most_played_title_opens_it_in_search(qapp, file_db):
    """A Most played row is a link like a region: it hands that title's channels here to Search."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    _seed(file_db)
    _play(file_db, "trex", "fut", 12, title="Futurama", media="series")
    _play(file_db, "trex", "fut", 7, title="Futurama", media="series")   # a second row, same title
    _play(file_db, "prosat", "fut", 3, title="Futurama", media="series")  # another source's copy
    ed = _analytics(qapp, file_db)
    try:
        got = []
        ed.browse_ids_requested.connect(lambda label, ids: got.append((label, ids)))
        link = next(w for w in ed._analytics_tab._viewing.findChildren(QLabel)
                    if w.toolTip() == "Show Futurama in Search")
        for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
            qapp.sendEvent(link, QMouseEvent(kind, QPointF(4, 4), QPointF(4, 4), Qt.MouseButton.LeftButton,
                                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        assert got and got[0][0] == "Futurama" and len(got[0][1]) == 2     # TREX's two rows only
    finally:
        destroy_widget(ed)

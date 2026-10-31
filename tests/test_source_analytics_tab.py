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

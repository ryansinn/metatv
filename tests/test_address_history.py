"""Server addresses show WHEN requests failed, not just how often (Source Analytics Q22).

On the owner's TREX, vpn.trxdnscloud.ru read "5%" though it had worked 6,715
times and failed every request since 20 Oct: a dead address, not a flaky one.
The row now carries the requests as ticks, the last success, and which address
MetaTV tries first.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from metatv.core.database import ProviderDB
from tests.conftest import destroy_widget


@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _attempt(when: datetime, ok: bool, ms: int | None = None) -> dict:
    return {"timestamp": when.isoformat(), "success": ok, "response_time_ms": ms}


def _seed(db):
    start = datetime(2026, 10, 30, 8, 0)
    with db.session_scope() as s:
        s.add(ProviderDB(id="trex", name="TREX", type="xtream", url="http://dead.example", username="u",
                         password="p", is_active=True, urls=[
            # Stored out of order on purpose: the history must come back oldest first.
            {"url": "http://dead.example", "success_count": 6715, "failure_count": 3,
             "last_success": "2026-10-20T19:01:54",
             "recent_attempts": [_attempt(start + timedelta(hours=2), False),
                                 _attempt(start, True, 800), _attempt(start + timedelta(hours=1), False)]},
            {"url": "http://good.example", "success_count": 3, "failure_count": 0,
             "last_success": datetime.now().isoformat(),
             "recent_attempts": [_attempt(start, True, 900), _attempt(start + timedelta(hours=1), True, 1100)]},
        ]))


def test_history_comes_back_oldest_first_with_last_success_and_first_choice(file_db):
    from metatv.core.repositories import RepositoryFactory
    _seed(file_db)
    with file_db.session_scope() as s:
        out = {a.url: a for a in RepositoryFactory(s).analytics.server_addresses("trex")}
    dead, good = out["http://dead.example"], out["http://good.example"]
    assert dead.history == (True, False, False)
    assert dead.last_worked == datetime(2026, 10, 20, 19, 1, 54)
    assert good.in_use and not dead.in_use            # the ranker puts the healthy one first


def test_first_choice_is_read_only():
    from metatv.core.models import Provider, ProviderURL
    from metatv.core.url_cycle import UrlCycler
    provider = Provider(id="p", name="P", type="xtream", url="http://a.example",
                        urls=[ProviderURL(url="http://a.example"), ProviderURL(url="http://b.example")])
    before = [(u.success_count, u.failure_count, len(u.recent_attempts)) for u in provider.urls]
    assert UrlCycler(provider, "t").first_choice() in ("http://a.example", "http://b.example")
    assert [(u.success_count, u.failure_count, len(u.recent_attempts)) for u in provider.urls] == before


def test_ticks_paint_worked_tall_and_failed_short_newest_on_the_right(qapp):
    from metatv.gui import theme as _theme
    from metatv.gui.attempt_ticks import SLOTS, AttemptTicks
    from metatv.gui.token_color import to_qcolor
    ticks = AttemptTicks((True, False, False))
    img = ticks.grab().toImage()
    ok, bad = to_qcolor(_theme.COLOR_ACCENT).name(), to_qcolor(_theme.COLOR_WARN).name()

    def column(i):
        r = ticks.tick_rect(i)
        return [img.pixelColor(r.left(), y).name() for y in range(r.top(), r.bottom() + 1)]

    assert column(0).count(ok) == ticks.height()            # worked: full height
    assert 0 < column(2).count(bad) <= 4 and ok not in column(2)  # failed: short, warning colour
    assert ticks.tick_rect(2).right() >= ticks.width() - 2   # the newest sits at the right edge
    assert ticks.tick_rect(0).left() == (SLOTS - 3) * (ticks.width() // SLOTS)
    assert ticks.toolTip().startswith("1 of the last 3 requests worked")


def test_the_card_names_the_address_in_use_and_when_each_last_worked(qapp, file_db):
    from PyQt6.QtWidgets import QLabel

    from metatv.gui.attempt_ticks import AttemptTicks
    from metatv.gui.provider_editor import ProviderEditorView
    _seed(file_db)
    ed = ProviderEditorView(file_db)
    ed.resize(1300, 900)
    ed.show()
    ed._tabs.setCurrentWidget(ed._analytics_scroll)
    ed.load_provider("trex")
    qapp.processEvents()
    try:
        card = ed._analytics_tab._addresses
        assert card.subtitle.text() == "1 of 2 have worked · in use: good.example" or \
            card.subtitle.text().endswith("in use: good.example")
        texts = [lbl.text() for lbl in card.findChildren(QLabel) if lbl.isVisible()]
        assert "today" in texts and "20 Oct" in texts and "Last worked" in texts
        assert len([t for t in card.findChildren(AttemptTicks) if t.isVisible()]) == 2
    finally:
        destroy_widget(ed)

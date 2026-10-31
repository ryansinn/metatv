"""The Sources manager's chip strip (owner, 2026-10-31).

A fixed 280 px left column of source rows became a strip of chips over a
full-width editor: icon · status dot · the first 14 characters of the name,
with expired / disabled / days left on a smaller second line. Asserted on the
rendered view — where the editor sits, how chips wrap, what the selected chip
paints — plus the chip's words.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from tests.conftest import destroy_widget


@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _provider(db, pid, name, *, active=True, expires_in_days=None):
    from metatv.core.database import ProviderDB
    exp = None if expires_in_days is None else datetime.now() + timedelta(days=expires_in_days, hours=1)
    with db.session_scope() as s:
        s.add(ProviderDB(id=pid, name=name, type="xtream", url="http://x", username="u",
                         password="p", is_active=active, account_exp_date=exp))


def _view(qapp, db, width=1000):
    from metatv.gui.provider_editor import ProviderEditorView
    from metatv.gui.sources_manager_view import SourcesManagerView
    view = SourcesManagerView(SimpleNamespace(), db, ProviderEditorView(db))
    view.resize(width, 700)
    view.show()
    view.on_activate()
    qapp.processEvents()
    return view


def test_the_editor_gets_the_full_width(qapp, file_db):
    _provider(file_db, "a", "TREX Shared", expires_in_days=27)
    view = _view(qapp, file_db)
    try:
        ed = view._provider_editor
        left = ed.mapTo(view, ed.rect().topLeft()).x()
        assert left <= 2 and ed.width() >= view.width() - 4, (left, ed.width(), view.width())
    finally:
        destroy_widget(view)


def test_chip_name_subline_and_tooltip(qapp, file_db):
    _provider(file_db, "a", "A Source Name Longer Than Fourteen", expires_in_days=27)
    _provider(file_db, "b", "Off", active=False, expires_in_days=5)
    _provider(file_db, "c", "Gone", expires_in_days=-3)
    _provider(file_db, "d", "NoDate")
    view = _view(qapp, file_db)
    try:
        chips = view._chips
        assert chips["a"].name_label.text() == "A Source Name…"
        assert chips["a"].days_label.text() == "27 days left"
        assert chips["a"].toolTip() == "A Source Name Longer Than Fourteen · Active · 27 days left"
        assert chips["b"].days_label.text() == "disabled · 5 days left"
        assert chips["c"].days_label.text() == "expired"
        assert chips["d"].days_label.isHidden(), "no expiry date, no second line"
    finally:
        destroy_widget(view)


def test_many_sources_wrap_inside_the_view(qapp, file_db):
    for i in range(8):
        _provider(file_db, f"p{i}", f"Source number {i}", expires_in_days=30)
    view = _view(qapp, file_db, width=700)
    try:
        chips = list(view._chips.values())
        tops = {c.mapTo(view, c.rect().topLeft()).y() for c in chips}
        assert len(tops) > 1, "eight chips at 700 px should wrap onto a second row"
        assert all(c.mapTo(view, c.rect().topRight()).x() < view.width() for c in chips)
    finally:
        destroy_widget(view)


def test_clicking_a_chip_selects_it_and_paints_it_selected(qapp, file_db):
    _provider(file_db, "a", "Alpha", expires_in_days=27)
    _provider(file_db, "b", "Beta", expires_in_days=27)
    view = _view(qapp, file_db)
    try:
        first = view._selected_id
        other = "b" if first == "a" else "a"
        before = view._chips[other].grab().toImage()
        view._chips[other].click()
        QApplication.processEvents()
        assert view._selected_id == other
        assert view._provider_editor._provider_id == other
        after = view._chips[other].grab().toImage()
        assert after.pixelColor(1, after.height() // 2) != before.pixelColor(1, before.height() // 2), (
            "the selected chip must paint differently (its border)")
    finally:
        destroy_widget(view)

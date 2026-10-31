"""WIP-2: the Sources editor wraps instead of clipping at common widths.

The editor's minimum width used to be ~542 px, set by things that never wrap
(an 85-character group title, four action buttons in a fixed row, a footer of
fixed-width buttons, long form rows), and the tab scroll areas hid that from
the layout — so beside the 280 px source list, the editor was clipped at its
right edge ("Refresh Guid…", "Refresh A…"). These render the real editor and
assert on painted geometry: at a narrow width every button is fully on screen,
and the minimum the editor reports is the minimum it needs.
"""

from __future__ import annotations

import uuid

import pytest
from PyQt6.QtWidgets import QAbstractButton, QApplication, QToolButton

from tests.conftest import destroy_widget

#: Comfortably below the old ~542 px floor; the fix brought it to ~340.
NARROW = 400


@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _editor(qapp, db, width: int):
    from metatv.core.database import ProviderDB
    from metatv.gui.provider_editor import ProviderEditorView
    pid = str(uuid.uuid4())
    urls = [{"url": f"http://a-rather-long-address-number-{i}.example-iptv-host.com:8080",
             "priority": i, "is_active": True, "success_count": 6715, "failure_count": 1135}
            for i in range(3)]
    with db.session_scope() as session:
        session.add(ProviderDB(id=pid, name="A Source With A Long Name", type="xtream",
                               url=urls[0]["url"], username="u", password="p",
                               is_active=True, account_status="Active", urls=urls))
    ed = ProviderEditorView(db)
    ed.load_provider(pid)
    ed.resize(width, 760)
    ed.show()
    qapp.processEvents()
    return ed


def _offscreen_buttons(ed, qapp) -> list[str]:
    """Buttons whose painted right edge falls outside the visible area, per tab."""
    bad = []
    for i in range(ed._tabs.count()):
        ed._tabs.setCurrentIndex(i)
        qapp.processEvents()
        scroll = ed._tabs.widget(i)
        vp = scroll.viewport()
        for btn in scroll.widget().findChildren(QAbstractButton):
            if isinstance(btn, QToolButton) or not btn.isVisible():
                continue   # QLineEdit clear buttons
            right = btn.mapTo(vp, btn.rect().topRight()).x()
            if right >= vp.width():
                bad.append(f"{ed._tabs.tabText(i)}: {btn.text()!r} right={right} > {vp.width()}")
    for btn in (ed._delete_btn, ed._test_btn, ed._discard_btn, ed._save_btn):
        right = btn.mapTo(ed, btn.rect().topRight()).x()
        if right >= ed.width():
            bad.append(f"footer: {btn.text()!r} right={right} > {ed.width()}")
    return bad


def test_every_button_is_on_screen_at_a_narrow_width(qapp, file_db):
    ed = _editor(qapp, file_db, NARROW)
    try:
        assert ed.width() == NARROW, f"the editor refused {NARROW}px (min {ed.minimumSizeHint().width()})"
        assert _offscreen_buttons(ed, qapp) == []
    finally:
        destroy_widget(ed)


def test_the_reported_minimum_is_what_the_content_needs(qapp, file_db):
    """The scroll areas must pass their content's width up, or the editor
    claims to fit where it clips — the mechanism behind the original bug."""
    ed = _editor(qapp, file_db, 900)
    try:
        assert ed.minimumSizeHint().width() <= NARROW
        for i in range(ed._tabs.count()):
            scroll = ed._tabs.widget(i)
            assert scroll.minimumSizeHint().width() >= scroll.widget().minimumSizeHint().width(), (
                ed._tabs.tabText(i))
    finally:
        destroy_widget(ed)


def test_action_bar_stays_right_aligned_when_wide(qapp, file_db):
    ed = _editor(qapp, file_db, 900)
    try:
        ed._tabs.setCurrentIndex(0)
        qapp.processEvents()
        content = ed._tabs.widget(0).widget()
        last = ed._action_toggle_btn
        right = last.mapTo(content, last.rect().topRight()).x()
        margin = content.layout().contentsMargins().right()
        assert content.width() - margin - right <= 2, "the action bar drifted off the right edge"
    finally:
        destroy_widget(ed)


def test_copy_label_shortens_but_copies_the_full_address(qapp):
    from metatv.gui.url_row_widget import _ClickToCopyLabel
    url = "http://a-rather-long-address.example-iptv-host.com:8080/xmltv.php?username=u&password=p"
    lbl = _ClickToCopyLabel(url)
    assert lbl.minimumSizeHint().width() < lbl.fontMetrics().horizontalAdvance(url) // 4
    assert lbl.text() == url and url in lbl.toolTip()
    lbl.copy()
    assert QApplication.clipboard().text() == url

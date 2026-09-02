"""Behavioral tests for the redesigned provider-editor URL row/list:

* click-to-copy on the URL text (no dedicated copy button)
* remove -> undoable ghost row (no confirmation dialog), Save is what deletes
* the URL list fills the pane instead of capping at ~4-5 rows

Companion to ``test_url_reliability_tint.py`` (the row's tint behaviour) and
``test_url_try_first.py`` (the one-shot try-first boost, core-layer). These
drive the real widgets/real editor — never a shape-only assertion — per the
project's "prove behavior" and "UI tests must assert rendered appearance"
rules.
"""

from __future__ import annotations

import uuid

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from metatv.core.models import ProviderURL


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture()
def file_db(tmp_path):
    """File-backed Database (not :memory:) so pooled connections share tables."""
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_provider(db, n_urls: int = 2, name: str = "TestProv") -> tuple[str, list[str]]:
    """Insert a ProviderDB row with *n_urls* fresh (untested) URLs. Returns
    (provider_id, [url, ...]) in seeded order."""
    from metatv.core.database import ProviderDB
    pid = str(uuid.uuid4())
    urls = [f"http://host{i}.example:8080" for i in range(n_urls)]
    raw = [
        {"url": u, "priority": i, "is_active": True, "success_count": 0, "failure_count": 0}
        for i, u in enumerate(urls)
    ]
    with db.session_scope() as session:
        session.add(ProviderDB(
            id=pid, name=name, type="xtream", url=urls[0],
            username="u1", password="pass", urls=raw,
        ))
    return pid, urls


# ── 5: click-to-copy ─────────────────────────────────────────────────────────

def test_clicking_the_url_label_copies_the_full_url(qapp, qtbot):
    from metatv.gui.url_row_widget import URLRowWidget, _ClickToCopyLabel

    pu = ProviderURL(url="http://example.com:8080/some/path")
    row = URLRowWidget(pu, 0, 1)
    qtbot.addWidget(row)

    label = row.findChild(_ClickToCopyLabel)
    assert label is not None, "the URL label must be a _ClickToCopyLabel"

    QApplication.clipboard().setText("")  # prove the click did it, not a stale value
    qtbot.mouseClick(label, Qt.MouseButton.LeftButton)

    assert QApplication.clipboard().text() == "http://example.com:8080/some/path"


# ── 6: remove -> ghost row -> undo, and Save is what actually deletes ──────

def test_remove_flips_to_ghost_row_not_immediate_deletion(qapp, file_db):
    """× must not delete anything immediately — it flips the row to
    pending-remove (ghost row + Undo), and the row stays present."""
    from metatv.gui.provider_editor import ProviderEditorView

    pid, urls = _seed_provider(file_db, n_urls=2)
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)
    assert ed._url_list.count() == 2

    target = ed._provider_urls[0].url
    ed._remove_url(0)

    assert target in ed._pending_url_removals
    assert ed._url_list.count() == 2, "the row must still be present (ghost), not gone"
    assert any(pu.url == target for pu in ed._provider_urls), (
        "removal must not touch the in-memory list until Save"
    )
    ghost_row = ed._url_list.itemWidget(ed._url_list.item(0))
    assert ghost_row._pending_remove is True


def test_undo_restores_a_pending_removal(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView

    pid, urls = _seed_provider(file_db, n_urls=2)
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)

    target = ed._provider_urls[0].url
    ed._remove_url(0)
    assert target in ed._pending_url_removals

    ed._restore_url(target)

    assert target not in ed._pending_url_removals
    row = ed._url_list.itemWidget(ed._url_list.item(0))
    assert row._pending_remove is False


def test_save_deletes_urls_still_pending_removal(qapp, file_db):
    """Save is what actually removes a ghost row's URL — from the persisted
    row AND from the editor's in-memory list."""
    from metatv.core.database import ProviderDB
    from metatv.gui.provider_editor import ProviderEditorView

    pid, urls = _seed_provider(file_db, n_urls=2)
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)

    removed_url = ed._provider_urls[0].url
    kept_url = ed._provider_urls[1].url
    ed._remove_url(0)

    ed._save()

    with file_db.session_scope(commit=False) as session:
        db_prov = session.query(ProviderDB).filter_by(id=pid).first()
        saved_urls = [u["url"] for u in db_prov.urls]

    assert removed_url not in saved_urls, "Save must actually delete a ghosted URL"
    assert kept_url in saved_urls
    assert ed._pending_url_removals == set(), "the pending set must clear after a successful save"
    assert all(pu.url != removed_url for pu in ed._provider_urls), (
        "the ghosted URL must also be dropped from the in-memory list, or it "
        "would reappear un-ghosted the next time the list is rebuilt"
    )


def test_a_restored_url_survives_save(qapp, file_db):
    """Undo before Save must keep the URL — the ghost/undo cycle must be a
    genuine no-op when the user changes their mind."""
    from metatv.core.database import ProviderDB
    from metatv.gui.provider_editor import ProviderEditorView

    pid, urls = _seed_provider(file_db, n_urls=2)
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)

    target = ed._provider_urls[0].url
    ed._remove_url(0)
    ed._restore_url(target)
    ed._save()

    with file_db.session_scope(commit=False) as session:
        db_prov = session.query(ProviderDB).filter_by(id=pid).first()
        saved_urls = {u["url"] for u in db_prov.urls}

    assert set(urls) == saved_urls


# ── 7: rendered appearance — the list fills the pane ────────────────────────
#
# The old code hard-capped the list at `min(total * 62, 62 * 5) == 310`px
# regardless of how much room the window actually had (the docstring it
# shipped under claimed "~4 rows"/~250px, but the arithmetic caps at 5 rows —
# 310px; either way the cap is FIXED, so a tall window changes nothing).
# 400 is comfortably above that fixed ceiling and comfortably below what the
# new Expanding policy actually produces in a 900px-tall window, so it
# discriminates the fix from the regression it fixes.

def test_url_list_fills_the_pane_in_a_tall_window(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView

    pid, urls = _seed_provider(file_db, n_urls=6)
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)
    ed._tabs.setCurrentIndex(1)  # Connection tab, where the URL list lives
    ed.resize(700, 900)
    ed.show()
    QApplication.processEvents()
    QApplication.processEvents()

    height = ed._url_list.height()
    ed.hide()

    assert height > 400, (
        f"URL list did not grow to fill a tall pane (height={height}px); "
        "the old fixed cap tops out at 310px regardless of window size"
    )

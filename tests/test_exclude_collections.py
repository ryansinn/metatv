"""Exclude a collection, keyed by source (owner, 2026-11-01).

(a) Engine — excluding (source A, "Au Espn Play") hides A's channels in that
    collection and nothing on source B with the same collection name; the SQL
    clause and the id-set twin agree.
(b) Repository — ``collections_for`` names every collection a title's copies
    sit in, with source name and size.
(c) Actions — the row-menu action reads "Exclude collection "X"" for one and
    opens a picker for several; exclude/include write the config and offer Undo.
(d) Menus — the details collection chip offers Exclude (or Include again);
    the "Available in" chip has ONE exclude row, not the old duplicate pair.
(e) Dialog — an excluded collection is listed checked; unchecking includes it.

Real ``Database`` on a ``tmp_path`` file, per the tests rule.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QMenu

from metatv.core.config import Config
from metatv.core.database import ChannelDB, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.tag_exclusions import (
    excluded_channel_ids,
    excluded_tag_content_types,
    tag_content_type_exclusion_criterion,
)


def _add(session, pid, collection):
    cid = str(uuid.uuid4())
    session.add(ChannelDB(id=cid, source_id=cid, provider_id=pid, name=f"{pid} {collection}",
                          media_type="live"))
    session.flush()
    RepositoryFactory(session).tags.set_content_tags(cid, [("collection", collection, "test")])
    return cid


@pytest.fixture
def seeded(file_db):
    with file_db.session_scope() as s:
        s.add(ProviderDB(id="pA", name="Source A", type="xtream", url="http://a.example", is_active=True))
        s.add(ProviderDB(id="pB", name="Source B", type="xtream", url="http://b.example", is_active=True))
        ids = {
            "a_espn": _add(s, "pA", "Au Espn Play"),
            "a_espn2": _add(s, "pA", "Au Espn Play"),
            "b_espn": _add(s, "pB", "Au Espn Play"),
            "a_news": _add(s, "pA", "News"),
        }
    return ids, file_db


def _visible(db, slugs):
    with db.session_scope() as s:
        q = s.query(ChannelDB.id).filter(tag_content_type_exclusion_criterion(slugs, ChannelDB.channel_key))
        return {cid for (cid,) in q.all()}


# ── (a) Engine ────────────────────────────────────────────────────────────────


def test_excluding_a_collection_hides_only_that_source(seeded):
    ids, db = seeded
    slugs = excluded_tag_content_types(Config(global_filter_excluded_collections=[["pA", "Au Espn Play"]]))
    visible = _visible(db, slugs)
    assert ids["a_espn"] not in visible and ids["a_espn2"] not in visible
    assert ids["b_espn"] in visible, "the same collection name on another source stays"
    assert ids["a_news"] in visible
    with db.session_scope() as s:
        assert excluded_channel_ids(s, slugs) == {ids["a_espn"], ids["a_espn2"]}


# ── (b) Repository ────────────────────────────────────────────────────────────


def test_collections_for_lists_each_source_collection_with_its_size(seeded):
    ids, db = seeded
    with db.session_scope() as s:
        got = RepositoryFactory(s).tags.collections_for([ids["a_espn"], ids["b_espn"]])
    assert ("pA", "Source A", "Au Espn Play", 2) in got
    assert ("pB", "Source B", "Au Espn Play", 1) in got
    assert got[0][3] == 2, "largest first"


# ── (c) Actions ───────────────────────────────────────────────────────────────


def test_row_menu_label_for_one_and_several_collections():
    from metatv.gui.channel_menu import ACTIONS, ChannelMenuContext

    act = ACTIONS["exclude_collection"]
    one = ChannelMenuContext(channel_ids=["x"], surface="channel",
                             collections=[("pA", "Source A", "Au Espn Play", 2)])
    two = ChannelMenuContext(channel_ids=["x"], surface="channel",
                             collections=[("pA", "Source A", "Au Espn Play", 2), ("pB", "Source B", "Espn", 1)])
    none = ChannelMenuContext(channel_ids=["x"], surface="channel")
    assert act.label(one) == 'Exclude collection "Au Espn Play"'
    assert act.label(two) == "Exclude collection…"
    assert act.applies(one) and act.applies(two) and not act.applies(none)


def _host(cfg):
    from metatv.gui.main_window_exclusions import _ExclusionActionsMixin as M

    host = SimpleNamespace(
        config=cfg, _update_filter_btn_state=MagicMock(), load_channels=MagicMock(),
        details_pane=SimpleNamespace(current_channel=None),
        notification_manager=SimpleNamespace(show=MagicMock()),
    )
    for name in ("is_collection_excluded", "_after_exclusion_change", "_on_collection_exclude",
                 "_on_collection_include", "_exclude_collection_from_menu"):
        setattr(host, name, getattr(M, name).__get__(host))
    return host


def test_exclude_then_undo_round_trips_the_config():
    cfg = Config()
    host = _host(cfg)
    ctx = SimpleNamespace(collections=[("pA", "Source A", "Au Espn Play", 2)])
    host._exclude_collection_from_menu(ctx, 0, 0)
    assert cfg.global_filter_excluded_collections == [["pA", "Au Espn Play"]]
    host.load_channels.assert_called_once()
    _title, undo = host.notification_manager.show.call_args.kwargs["actions"][0]
    undo()
    assert cfg.global_filter_excluded_collections == []


# ── (d) Menus ─────────────────────────────────────────────────────────────────


def _capture_menu(monkeypatch, choose: str | None = None):
    """Record every QMenu's action texts; optionally 'click' the one starting with *choose*."""
    seen: list[list[str]] = []

    def fake_exec(menu, *_a, **_k):
        texts = [a.text() for a in menu.actions()]
        seen.append(texts)
        if choose:
            return next((a for a in menu.actions() if a.text().startswith(choose)), None)
        return None

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    return seen


def test_collection_chip_menu_excludes_this_source_collection(qtbot, monkeypatch):
    from metatv.gui.details_title import _MetadataSection

    w = _MetadataSection(Config())
    qtbot.addWidget(w)
    w._source_provider_id, w._source_name, w._collection_value = "pA", "Source A", "Au Espn Play"
    seen = _capture_menu(monkeypatch, choose="Exclude")
    with qtbot.waitSignal(w.collection_exclude_requested) as sig:
        w._on_collection_chip_menu(w._collection_chip.rect().center())
    assert sig.args == ["pA", "Au Espn Play"]
    assert 'Exclude the "Au Espn Play" collection' in seen[0]

    w.collection_excluded = lambda _p, _v: True
    _capture_menu(monkeypatch, choose="Include")
    with qtbot.waitSignal(w.collection_include_requested):
        w._on_collection_chip_menu(w._collection_chip.rect().center())


def test_available_in_chip_has_one_exclude_row(qtbot, monkeypatch):
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    w = _VersionSection(Config())
    qtbot.addWidget(w)
    v = ChannelVersion(channel_id="c1", name="Some Film", in_queue=False, detected_prefix="TR")
    seen = _capture_menu(monkeypatch)
    w._show_version_chip_menu(w.mapToGlobal(w.rect().center()), v)
    texts = seen[0]
    assert 'Exclude all "TR" content' in texts
    assert not any(t.startswith(("Filter out ALL", "Hide the")) for t in texts), "the duplicate pair is gone"


# ── (e) Dialog ────────────────────────────────────────────────────────────────


def test_dialog_lists_excluded_collection_and_unchecking_includes_it(seeded, qtbot):
    from metatv.gui.global_filter_dialog import GlobalFilterDialog

    _ids, db = seeded
    cfg = Config(global_filter_excluded_collections=[["pA", "Au Espn Play"]])
    dlg = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    section = dlg._tag_sections["collection"]
    (cb,) = section._checkboxes.values()
    assert cb.text() == "Au Espn Play · Source A" and cb.isChecked()
    assert cb.parentWidget().isVisible(), "the excluded collection is shown, not folded away"
    cb.setChecked(False)
    dlg._save_and_accept()
    assert cfg.global_filter_excluded_collections == []

"""Behavioral tests: off-thread provider-delete + content_tags prune/cleanup.

Guards the confirmed bug + its two-part fix:

* Part A — the purge runs OFF the Qt UI thread.  ``ProviderEditorView`` now only
  confirms + emits ``provider_delete_requested``; the ``MainWindow`` owner submits
  the purge to its executor and marshals the result back through
  ``_provider_delete_finished`` to a main-thread slot that resets the editor and
  runs the canonical view refresh.  These drive the real seam methods with a
  synchronous executor (deterministic) against a real file-backed ``Database``.

* Part B — ``prune_provider_content`` now removes ``content_tags`` (no FK cascade,
  so they were leaked before) for the doomed channels, sparing engaged channels'
  tags; and a one-time ``_prune_orphaned_content_tags`` migration heals the
  pre-existing backlog.

Per CLAUDE.md every test uses a real ``Database`` on a ``tmp_path`` file — never
``:memory:`` (pooled in-memory connections don't share schema / ``user_version``).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import (
    Database, ProviderDB, ChannelDB, TagDB, ContentTagDB,
)
from metatv.core.repositories.channel import ChannelRepository
from metatv.core.repositories.provider import ProviderRepository
from metatv.gui.main_window import MainWindow


# Unbound seam methods (driven with a SimpleNamespace `self`, like
# test_post_refresh_resweep.py) — avoids constructing a real QMainWindow.
_REQUEST = MainWindow._on_provider_delete_requested
_FINISHED = MainWindow._on_provider_delete_finished


# ── Fixtures & helpers ───────────────────────────────────────────────────────


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'delete_offthread.db'}")
    d.create_tables()
    yield d
    d.close()


class _SyncExecutor:
    """Runs submitted work inline so the deliberately off-thread hop is
    deterministic in tests (production submits to ``self.executor``)."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return None


def _provider(session, pid: str) -> str:
    session.add(ProviderDB(
        id=pid, name=f"Provider {pid}", type="xtream",
        url="http://example.com", username="u", password="p",
    ))
    session.flush()
    return pid


def _channel(session, provider_id: str, *, cid: str = None,
             is_favorite: bool = False) -> str:
    cid = cid or str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid, source_id=cid, provider_id=provider_id,
        name=f"Chan {cid[:8]}", media_type="movie",
        is_favorite=is_favorite,
    ))
    session.flush()
    return cid


def _tag(session, value: str) -> int:
    t = TagDB(type="genre", value=value)
    session.add(t)
    session.flush()
    return t.id


def _content_tag(session, channel_id: str, tag_id: int) -> None:
    session.add(ContentTagDB(
        channel_id=channel_id, tag_id=tag_id,
        source="generated", feeders=["rule:test"], confidence=1.0,
    ))
    session.flush()


# ── Part B: content_tags pruned for doomed, spared for engaged ───────────────


def test_prune_deletes_content_tags_of_nonengaged_and_spares_engaged(db):
    """The content_tags leak fix: a non-engaged channel's tag links are deleted;
    an engaged (favorited) channel's tag links survive the provider purge."""
    pid = "pid-ct"
    ne_id = "ch-ne"
    eng_id = "ch-eng"
    with db.session_scope() as session:
        _provider(session, pid)
        _channel(session, pid, cid=ne_id)               # non-engaged
        _channel(session, pid, cid=eng_id, is_favorite=True)  # engaged
        t1 = _tag(session, "Action")
        t2 = _tag(session, "Drama")
        _content_tag(session, ne_id, t1)    # doomed
        _content_tag(session, ne_id, t2)    # doomed
        _content_tag(session, eng_id, t1)   # must survive (engaged channel)

    with db.session_scope() as session:
        counts = ChannelRepository(session).prune_provider_content([pid])

    assert counts["content_tags"] == 2, "both doomed-channel tag links must be counted"

    with db.session_scope(commit=False) as session:
        assert session.query(ContentTagDB).filter_by(channel_id=ne_id).count() == 0, \
            "non-engaged channel's content_tags must be pruned"
        assert session.query(ContentTagDB).filter_by(channel_id=eng_id).count() == 1, \
            "engaged channel's content_tags must be preserved"
        # Sanity: the doomed channel is gone, the engaged one remains.
        assert session.query(ChannelDB).filter_by(id=ne_id).first() is None
        assert session.query(ChannelDB).filter_by(id=eng_id).first() is not None


def test_prune_content_tags_via_provider_delete(db):
    """End-to-end through ProviderRepository.delete(): a deleted provider's
    non-engaged content_tags are removed."""
    pid = "pid-del"
    ch = "ch-del"
    with db.session_scope() as session:
        _provider(session, pid)
        _channel(session, pid, cid=ch)
        t = _tag(session, "Comedy")
        _content_tag(session, ch, t)

    with db.session_scope() as session:
        assert ProviderRepository(session).delete(pid) is True

    with db.session_scope(commit=False) as session:
        assert session.query(ContentTagDB).filter_by(channel_id=ch).count() == 0


# ── Part A: the off-thread delete seam ───────────────────────────────────────


def _seam_self(db_obj, *, on_deleted, sources=None):
    me = SimpleNamespace()
    # Wave 6: Sources left the sidebar stack — expose the mixin's resolver.
    me._sources_status_target = lambda: sources
    me.db = db_obj
    me.executor = _SyncExecutor()
    me.notification_manager = MagicMock()
    me.notification_manager.show_progress.return_value = "notif-del"
    me.provider_editor = MagicMock()
    me.sidebar_sections = {"sources": sources} if sources is not None else {}
    me._provider_delete_notifs = {}
    me._on_provider_deleted = on_deleted
    # Emulate the queued signal → slot: emit(...) invokes the finished slot now.
    me._provider_delete_finished = SimpleNamespace(
        emit=lambda pid, ok, err: _FINISHED(me, pid, ok, err)
    )
    return me


def test_delete_seam_runs_purge_offthread_then_refreshes(db):
    """The real seam: _on_provider_delete_requested submits the purge to the
    executor (real delete against a real DB), and the finished slot resets the
    editor + routes through _on_provider_deleted (canonical refresh)."""
    pid = "pid-seam"
    ch = "ch-seam"
    with db.session_scope() as session:
        _provider(session, pid)
        _channel(session, pid, cid=ch)
        t = _tag(session, "SciFi")
        _content_tag(session, ch, t)

    on_deleted = MagicMock()
    sources = MagicMock()
    me = _seam_self(db, on_deleted=on_deleted, sources=sources)

    _REQUEST(me, pid)  # drives the whole seam synchronously via the fake executor

    # The purge actually ran: provider + its non-engaged channel + tags are gone.
    with db.session_scope(commit=False) as session:
        assert session.query(ProviderDB).filter_by(id=pid).first() is None
        assert session.query(ChannelDB).filter_by(id=ch).first() is None
        assert session.query(ContentTagDB).filter_by(channel_id=ch).count() == 0

    # Canonical post-delete cleanup fired exactly once.
    on_deleted.assert_called_once_with(pid)
    # Toast shown then dismissed; editor disabled then re-enabled.
    me.notification_manager.show_progress.assert_called_once()
    me.notification_manager.dismiss.assert_called_once_with("notif-del")
    me.provider_editor.setEnabled.assert_any_call(False)
    me.provider_editor.setEnabled.assert_any_call(True)
    # Source row busy toggled on then off.
    sources.set_provider_busy.assert_any_call(pid, True)
    sources.set_provider_busy.assert_any_call(pid, False)
    # No entry left in the in-flight tracking dict.
    assert me._provider_delete_notifs == {}


def test_delete_seam_failure_surfaces_error_and_skips_cleanup(db):
    """A delete that reports failure (unknown provider → deleted=False) must show
    an error toast and NOT run the canonical delete-cleanup."""
    on_deleted = MagicMock()
    me = _seam_self(db, on_deleted=on_deleted)

    _REQUEST(me, "no-such-provider")

    on_deleted.assert_not_called()
    me.notification_manager.dismiss.assert_called_once_with("notif-del")
    me.provider_editor.setEnabled.assert_any_call(True)  # re-enabled even on failure
    # An error toast was raised.
    assert me.notification_manager.show.called


def test_delete_requested_noop_on_empty_provider_id(db):
    """An empty provider_id must be ignored (no toast, no executor work)."""
    me = _seam_self(db, on_deleted=MagicMock())
    _REQUEST(me, "")
    me.notification_manager.show_progress.assert_not_called()


# ── Part B: one-time orphaned-content_tags cleanup migration ─────────────────


def test_orphaned_content_tags_migration_heals_backlog(tmp_path):
    """create_tables() removes content_tags whose channel no longer exists, keeps
    valid ones, and is idempotent on a second run (user_version=3 gate)."""
    db_file = tmp_path / "ct_heal.db"

    # Build a raw DB (no migrations) with a valid channel + a valid tag link and an
    # orphaned tag link (channel_id points at a channel that was never inserted).
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from metatv.core.database import Base

    raw_engine = create_engine(f"sqlite:///{db_file}", echo=False,
                               connect_args={"check_same_thread": False})
    Base.metadata.create_all(raw_engine)
    RawSession = sessionmaker(bind=raw_engine)

    live_ch = str(uuid.uuid4())
    with RawSession() as s:
        s.add(ProviderDB(id="p1", name="P1", type="xtream",
                         url="http://x", username="u", password="p"))
        s.add(ChannelDB(id=live_ch, source_id=live_ch, provider_id="p1",
                        name="Live", media_type="movie"))
        s.add(TagDB(id=1, type="genre", value="Action"))
        # Valid link (channel exists)
        s.add(ContentTagDB(channel_id=live_ch, tag_id=1, source="generated"))
        # Orphaned link (channel_id "ghost" has no channels row)
        s.add(ContentTagDB(channel_id="ghost", tag_id=1, source="generated"))
        s.commit()
    raw_engine.dispose()

    # create_tables() triggers the one-time content_tags cleanup migration.
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()

    with db.session_scope(commit=False) as session:
        assert session.query(ContentTagDB).filter_by(channel_id="ghost").count() == 0, \
            "orphaned content_tags must be removed by the one-time migration"
        assert session.query(ContentTagDB).filter_by(channel_id=live_ch).count() == 1, \
            "content_tags for a live channel must be preserved"
    db.close()

    # Second run: idempotent (user_version=3 gates it) — must not raise or delete more.
    db2 = Database(f"sqlite:///{db_file}")
    db2.create_tables()
    with db2.session_scope(commit=False) as session:
        assert session.query(ContentTagDB).filter_by(channel_id=live_ch).count() == 1
    db2.close()

"""Regression: audio facets require DetectedTitleReparse to run BEFORE TagBackfill.

The TagBackfill ``audio_annotation`` feeder reads ``ChannelDB.detected_audio``,
which is populated by ``DetectedTitleReparseTask`` (via ``update_detected_prefixes``).
If TagBackfill runs first it reads NULL and emits no ``subtitle:`` / ``dub:`` /
``format:`` facets — and because both tasks are version-gated, neither re-runs, so
the facets silently never appear on existing libraries until a manual source refresh.

These tests prove the dependency behaviorally (not the registration order's shape):

* wrong order  → TagBackfill alone (detected_audio still NULL) yields NO subtitle facet
* correct order → DetectedTitleReparse THEN TagBackfill yields ``subtitle:English``

The migration registration in ``main_window.py`` must keep DetectedTitleReparse
ahead of TagBackfill so production matches the "correct order" case.

All DB tests use file-backed SQLite (tmp_path) per CLAUDE.md — not :memory:.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _noop_progress(done: int, total: int) -> None:
    """No-op progress callback for driving a MigrationTask.run() in tests."""


def _not_cancelled() -> bool:
    """Never-cancelled predicate for driving a MigrationTask.run() in tests."""
    return False


@pytest.fixture
def db(tmp_path: Path):
    """File-backed Database with tables created."""
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'audio_order_test.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture
def cfg(tmp_path: Path):
    """Config rooted at a throwaway dir (never touches the real user config)."""
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


def _seed_subbed_channel(db) -> str:
    """Insert one movie whose name carries an ENG-SUB annotation; return its id.

    detected_audio is left NULL — exactly the pre-migration state of an existing
    library row. "Film (SPANISH ENG-SUB)" parses to sub_langs=['English'].
    """
    from metatv.core.database import ChannelDB, ProviderDB

    cid = "ch-subbed-1"
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="p1", name="p1", type="xtream", url="http://e.com",
            username="u", password="p", is_active=True,
        ))
        session.add(ChannelDB(
            id=cid, source_id=cid, provider_id="p1",
            name="Film (SPANISH ENG-SUB)", media_type="movie",
            detected_audio=None,
        ))
    return cid


def _facet_values(db, channel_id: str, facet_type: str) -> set[str]:
    """Return the set of TagDB.value for one channel + facet type (e.g. 'subtitle')."""
    from metatv.core.database import ContentTagDB, TagDB

    with db.session_scope(commit=False) as session:
        rows = (
            session.query(TagDB.value)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(
                ContentTagDB.channel_id == channel_id,
                TagDB.type == facet_type,
            )
            .all()
        )
    return {r[0] for r in rows}


def test_tagbackfill_before_reparse_yields_no_audio_facet(db, cfg):
    """WRONG order: TagBackfill on NULL detected_audio emits no subtitle facet.

    This documents the bug the registration order guards against — the audio
    feeder has nothing to read, so the headline facet never lands.
    """
    from metatv.core.migrations.tag_backfill import TagBackfillTask

    cid = _seed_subbed_channel(db)

    TagBackfillTask(db, config=cfg).run(_noop_progress, _not_cancelled)

    assert _facet_values(db, cid, "subtitle") == set(), (
        "TagBackfill before DetectedTitleReparse must NOT produce a subtitle facet "
        "(detected_audio is still NULL) — this is the silent-miss the migration "
        "order exists to prevent"
    )


def test_reparse_then_tagbackfill_yields_subtitle_facet(db, cfg):
    """CORRECT order: DetectedTitleReparse populates detected_audio, then TagBackfill
    reads it and emits subtitle:English. This must match production registration order.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.migrations.detected_title_reparse import DetectedTitleReparseTask
    from metatv.core.migrations.tag_backfill import TagBackfillTask

    cid = _seed_subbed_channel(db)

    # 1. Reparse populates detected_audio from the name.
    DetectedTitleReparseTask(db).run(_noop_progress, _not_cancelled)

    with db.session_scope(commit=False) as session:
        ch = session.get(ChannelDB, cid)
        assert ch.detected_audio is not None, "reparse must populate detected_audio"
        assert "English" in (ch.detected_audio.get("sub") or []), (
            "detected_audio.sub must capture the English subtitle track"
        )

    # 2. TagBackfill now reads detected_audio and emits the audio facets.
    TagBackfillTask(db, config=cfg).run(_noop_progress, _not_cancelled)

    assert "English" in _facet_values(db, cid, "subtitle"), (
        "subtitle:English must be present once detected_audio is populated first"
    )

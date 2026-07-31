"""Behavioral tests for two cross-source dedup fixes (v0.13.0).

Fix C — control-char mojibake cleanup at ingestion
    A provider name carrying a stray C1 control char (e.g. U+0081 corrupting "Á"
    in "|ES| Alita: <U+0081>ngel de combate") must store a clean ``detected_title``
    and a clean title-fallback ``content_key`` — the non-printing artifact never
    reaches the stored fields.  The ``DetectedTitleReparse`` backfill (version 6)
    re-cleans a pre-existing corrupted row and recomputes its content_key.

Fix B — singleton-anchor lazy enrichment
    Viewing an idless row's details ALWAYS enqueues the anchor for provider-native
    TMDb enrichment, even when the row is a ``content_key`` singleton with no
    "Other Versions" — otherwise a corrupted/idless title is never attempted and
    never surfaces in the "Missing TMDb" diagnostic.  A harvested provider tmdb id
    flips the content_key to the tmdb-first form so cross-source variants collapse.

All DB tests use file-backed (tmp_path) SQLite per CLAUDE.md — never :memory:
(pooled connections each see an empty schema).
"""

from __future__ import annotations

import types
import uuid
from pathlib import Path

import pytest


# The exact corrupted title from the real library: "Á" of "Ángel" is rendered as a
# plain 'i' followed by a raw C1 control char U+0081 (0x81), a latin-1/UTF-8
# mishandling artifact.  parse_channel_name must strip the U+0081.
CORRUPT_NAME = "|ES| Alita: i\x81ngel de combate"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_channel(session, *, name: str, provider_id: str = "p1",
                  media_type: str = "movie", raw_data=None,
                  detected_title=None, content_key=None,
                  detected_tmdb_id=None) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        raw_data=raw_data,
        detected_title=detected_title,
        content_key=content_key,
        detected_tmdb_id=detected_tmdb_id,
    ))
    return cid


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables created."""
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'dedup_fixes.db'}")
    d.create_tables()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# Fix C — unit: clean_control_chars / parse_channel_name
# ---------------------------------------------------------------------------


class TestControlCharCleanup:
    """clean_control_chars removes non-printing controls; parse_channel_name applies it."""

    def test_clean_strips_c1_control_char(self):
        from metatv.core.channel_name_utils import clean_control_chars
        out = clean_control_chars(CORRUPT_NAME)
        assert "\x81" not in out, f"U+0081 must be stripped; got {out!r}"
        assert out == "|ES| Alita: ingel de combate", out

    def test_clean_strips_various_controls(self):
        from metatv.core.channel_name_utils import clean_control_chars
        # C0 (U+0007 BEL), DEL (U+007F), C1 (U+009F) all removed.
        assert clean_control_chars("A\x07B\x7fC\x9fD") == "ABCD"

    def test_clean_preserves_accented_and_clean_text(self):
        from metatv.core.channel_name_utils import clean_control_chars
        # A genuine accented letter (U+00C1 "Á") is printable and must survive.
        assert clean_control_chars("Alita: Ángel de combate") == "Alita: Ángel de combate"
        assert clean_control_chars("NF - Alita: Battle Angel") == "NF - Alita: Battle Angel"

    def test_clean_collapses_exposed_whitespace(self):
        from metatv.core.channel_name_utils import clean_control_chars
        # A control char flanked by spaces leaves a double space → collapsed to one.
        assert clean_control_chars("A \x81 B") == "A B"

    def test_clean_handles_falsy(self):
        from metatv.core.channel_name_utils import clean_control_chars
        assert clean_control_chars("") == ""
        assert clean_control_chars(None) is None

    def test_parse_channel_name_strips_control_char(self):
        from metatv.core.channel_name_utils import parse_channel_name
        parsed = parse_channel_name(CORRUPT_NAME)
        assert "\x81" not in parsed.bare_name, (
            f"control char leaked into bare_name: {parsed.bare_name!r}"
        )
        assert parsed.bare_name == "Alita: ingel de combate", parsed.bare_name
        assert parsed.region == "ES", parsed.region

    def test_parse_clean_name_unchanged(self):
        from metatv.core.channel_name_utils import parse_channel_name
        assert parse_channel_name("NF - Alita: Battle Angel").bare_name == "Alita: Battle Angel"
        # Legitimate numeric title survives (no over-strip regression).
        assert parse_channel_name("Blade Runner 2049").bare_name == "Blade Runner 2049"


# ---------------------------------------------------------------------------
# Fix C — end-to-end: ingestion stores a clean title + clean content_key
# ---------------------------------------------------------------------------


def test_ingested_corrupted_name_stores_clean_title_and_key(db):
    """update_detected_prefixes on a U+0081-corrupted name → clean detected_title + key."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid = _make_channel(session, name=CORRUPT_NAME, media_type="movie")

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        ch = session.query(ChannelDB).filter_by(id=cid).one()
        title = ch.detected_title
        key = ch.content_key

    assert title is not None
    assert "\x81" not in title, f"detected_title still carries U+0081: {title!r}"
    assert title == "Alita: ingel de combate", title
    assert key is not None
    assert "\x81" not in key, f"content_key still carries U+0081: {key!r}"
    # Title-fallback key (no provider tmdb id): clean, no stray glyph or double space.
    assert key == "alita ingel de combate|movie|", key


# ---------------------------------------------------------------------------
# Fix C — backfill migration repairs a PRE-EXISTING corrupted row
# ---------------------------------------------------------------------------


def test_reparse_backfill_repairs_preexisting_corrupted_row(db):
    """DetectedTitleReparseTask re-cleans a row stored (pre-fix) with a corrupted title.

    Simulates a row ingested before the fix: its ``detected_title`` and
    ``content_key`` carry the U+0081 artifact.  Running the reparse task
    re-derives both from the (still-corrupted) provider name — now through the
    control-char strip — and writes clean values.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.migrations.detected_title_reparse import DetectedTitleReparseTask

    # Pre-fix stored state: corrupted detected_title + polluted content_key.
    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name=CORRUPT_NAME,
            media_type="movie",
            detected_title="Alita: i\x81ngel de combate",
            content_key="alita i ngel de combate|movie|",
        )

    # Sanity: the seeded row really is corrupted before the migration runs.
    with db.session_scope(commit=False) as session:
        before = session.query(ChannelDB).filter_by(id=cid).one()
        assert "\x81" in before.detected_title
        assert "\x81" not in before.content_key  # key normaliser had turned it into a space

    task = DetectedTitleReparseTask(db)
    task.run(progress_cb=lambda done, total: None, is_cancelled=lambda: False)

    with db.session_scope(commit=False) as session:
        after = session.query(ChannelDB).filter_by(id=cid).one()
        title = after.detected_title
        key = after.content_key

    assert "\x81" not in title, f"backfill left U+0081 in detected_title: {title!r}"
    assert title == "Alita: ingel de combate", title
    assert key == "alita ingel de combate|movie|", key


def test_reparse_task_version_is_six(tmp_path: Path):
    """The reparse migration is bumped to version 6 (control-char strip) and gates on it."""
    from metatv.core.config import Config
    from metatv.core.migrations.detected_title_reparse import (
        DetectedTitleReparseTask, CURRENT_VERSION,
    )

    assert CURRENT_VERSION == 6, "control-char strip requires a full re-run (version 6)"

    config = Config(config_dir=tmp_path / "config")
    # A user already at version 5 must be re-run for the control-char strip.
    config.detected_reparse_version = 5
    task = DetectedTitleReparseTask.__new__(DetectedTitleReparseTask)
    assert task.needs_run(config) is True

    task.on_completed(config)
    assert config.detected_reparse_version == 6
    assert task.needs_run(config) is False


# ---------------------------------------------------------------------------
# Fix B — singleton anchor is enqueued for enrichment when its details are viewed
# ---------------------------------------------------------------------------


def _host_with_capture():
    """A MainWindow shell (via __new__) that captures _enqueue_tmdb_enrichment calls."""
    from metatv.gui.main_window import MainWindow

    host = MainWindow.__new__(MainWindow)
    host.details_pane = types.SimpleNamespace(current_channel=None, set_versions=lambda v: None)
    captured: list[list[str]] = []
    host._enqueue_tmdb_enrichment = lambda ids: captured.append(list(ids))  # type: ignore[method-assign]
    return host, captured


def test_singleton_anchor_enqueued_when_no_versions():
    """An idless content_key singleton (no Other Versions) still enqueues its anchor.

    Regression: the previous ``if versions:`` guard skipped the enqueue entirely
    when a row had no siblings, so a corrupted/idless singleton (like the mojibake
    Alita row) was never enrichment-attempted by viewing its details.
    """
    from metatv.gui.main_window_metadata import _MetadataMixin

    host, captured = _host_with_capture()
    _MetadataMixin._on_versions_loaded(host, "anchor-id", [])

    assert captured == [["anchor-id"]], (
        f"anchor must be enqueued even with no Other Versions; got {captured!r}"
    )


def test_anchor_and_siblings_enqueued_when_versions_present():
    """With Other Versions present, the anchor AND every sibling id are enqueued."""
    from metatv.gui.main_window_metadata import _MetadataMixin

    host, captured = _host_with_capture()
    versions = [
        types.SimpleNamespace(channel_id="sib-1"),
        types.SimpleNamespace(channel_id="sib-2"),
    ]
    _MetadataMixin._on_versions_loaded(host, "anchor-id", versions)

    assert len(captured) == 1
    assert captured[0] == ["anchor-id", "sib-1", "sib-2"], captured


# ---------------------------------------------------------------------------
# Fix B — a harvested provider tmdb id flips content_key to the tmdb-first form
# ---------------------------------------------------------------------------


def test_harvested_tmdb_id_flips_content_key_to_tmdb_first(db):
    """raw_data['tmdb'] is harvested into detected_tmdb_id → content_key becomes tmdb-first.

    Exercises the provider-native harvest path: an idless row whose raw list blob
    carries a tmdb id gets that id backfilled, and the recompute emits
    ``tmdb:{id}|{media_type}`` so cross-source/language variants collapse onto it.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="NF - Alita: Battle Angel",
            media_type="movie",
            raw_data={"tmdb": "399579"},
        )

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        # 1. Harvest raw_data['tmdb'] → detected_tmdb_id.
        wrote = repos.channels.backfill_tmdb_ids()
        assert wrote == 1, "the raw tmdb id should have been harvested"
        # 2. Recompute content_key from the now-stored id (tmdb-first).
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        ch = session.query(ChannelDB).filter_by(id=cid).one()
        assert ch.detected_tmdb_id == "399579", ch.detected_tmdb_id
        assert ch.content_key == "tmdb:399579|movie", ch.content_key

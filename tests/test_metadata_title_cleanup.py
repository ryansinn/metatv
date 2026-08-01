"""Behavioral tests for the metadata-title data cleanup (raw-name pollution fix).

Two deliverables are covered:

1. One-time migration ``Database._clean_polluted_metadata_titles`` (user_version 4)
   that heals ``metadata.title`` rows storing a raw channel name
   (e.g. ``EN - Cowboy Bebop (1998)``):
     - Pass 1 (join): title == a linked channel's raw ``name`` → copy that
       channel's clean ``detected_title``.
     - Pass 2 (parse fallback): a *linked* polluted title the exact-name join
       missed → replace with ``parse_channel_name(title).bare_name``.
     - Genuinely-clean and orphaned/unreachable titles are left untouched.

2. The ingestion path (``ProviderMetadataProvider.get_details``) that used to set
   ``title=info.get('name') or channel.name`` — now stores the clean
   ``detected_title`` when the provider only echoes the raw channel name back,
   while still honoring a real, distinct provider title.

Each test executes the changed path against a real ``Database`` on a tmp file
(never ``:memory:``) and asserts the outcome that would break on revert.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text

from metatv.core.database import ChannelDB, Database, MetadataDB


def _make_db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_tables()  # runs the migration once on the (empty) DB, stamping v4
    return db


def _set_user_version(db: Database, version: int) -> None:
    """Roll PRAGMA user_version back so the one-time migration will run again."""
    with db.engine.connect() as conn:
        conn.execute(text(f"PRAGMA user_version = {version}"))
        conn.commit()


def _metadata_title(db: Database, mid: str) -> str:
    with db.session_scope() as session:
        return session.query(MetadataDB).filter_by(id=mid).one().title


# ---------------------------------------------------------------------------
# Migration — _clean_polluted_metadata_titles
# ---------------------------------------------------------------------------

class TestMetadataTitleMigration:
    def test_pass1_join_replaces_raw_name_with_detected_title(self, tmp_path):
        """metadata.title == linked channel.name → cleaned to channel.detected_title."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            session.add(MetadataDB(id="m1", title="EN - Cowboy Bebop (1998)", source="provider"))
            session.add(ChannelDB(
                id="c1", source_id="c1", provider_id="p1",
                name="EN - Cowboy Bebop (1998)",
                detected_title="Cowboy Bebop", metadata_id="m1",
            ))

        _set_user_version(db, 3)          # un-stamp so the migration runs
        db._clean_polluted_metadata_titles()

        assert _metadata_title(db, "m1") == "Cowboy Bebop", (
            "Fallback metadata whose title is the raw channel name must be "
            "healed to the channel's clean detected_title"
        )

    def test_genuinely_clean_title_is_left_untouched(self, tmp_path):
        """A real, prefix-free title is not modified by the migration."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            session.add(MetadataDB(id="m2", title="Blade Runner", source="provider"))
            session.add(ChannelDB(
                id="c2", source_id="c2", provider_id="p1",
                name="Blade Runner", detected_title="Blade Runner", metadata_id="m2",
            ))

        _set_user_version(db, 3)
        db._clean_polluted_metadata_titles()

        assert _metadata_title(db, "m2") == "Blade Runner", (
            "A clean title (detected_title == name, nothing to strip) must be untouched"
        )

    def test_pass2_parse_fallback_cleans_linked_but_unmatched_title(self, tmp_path):
        """A linked polluted title the exact-name join missed is parse-cleaned."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            # metadata title is a raw name, but NO linked channel is named exactly
            # that (the source channel was renamed/removed; a sibling still links it).
            session.add(MetadataDB(id="m3", title="FR | Le Voyage (2001)", source="provider"))
            session.add(ChannelDB(
                id="c3", source_id="c3", provider_id="p1",
                name="FR | Le Voyage (2001) HD",   # differs → Pass 1 cannot match
                detected_title="Le Voyage", metadata_id="m3",
            ))

        _set_user_version(db, 3)
        db._clean_polluted_metadata_titles()

        assert _metadata_title(db, "m3") == "Le Voyage", (
            "Pass 2 must parse the raw name down to its bare_name when the "
            "exact-name join could not reach it"
        )

    def test_orphaned_polluted_title_is_left_untouched(self, tmp_path):
        """Polluted metadata reachable from no channel is not rewritten (linked-only gate)."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            session.add(MetadataDB(id="m4", title="DE - Foo (1999)", source="provider"))
            # No channel references m4.

        _set_user_version(db, 3)
        db._clean_polluted_metadata_titles()

        assert _metadata_title(db, "m4") == "DE - Foo (1999)", (
            "Unreachable (never-displayed) metadata is deliberately left alone"
        )

    def test_cleanup_fires_through_create_tables(self, tmp_path):
        """The real launch entry point (create_tables) runs the cleanup, not just
        the private method — guards against the wiring being dropped."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            session.add(MetadataDB(id="m6", title="EN - Cowboy Bebop (1998)", source="provider"))
            session.add(ChannelDB(
                id="c6", source_id="c6", provider_id="p1",
                name="EN - Cowboy Bebop (1998)",
                detected_title="Cowboy Bebop", metadata_id="m6",
            ))

        _set_user_version(db, 3)   # simulate a pre-v4 user DB
        db.create_tables()          # the actual startup path

        assert _metadata_title(db, "m6") == "Cowboy Bebop"

    def test_migration_is_idempotent_and_gated(self, tmp_path):
        """Re-running after the version stamp is a no-op and does not re-mangle."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            session.add(MetadataDB(id="m5", title="EN - Cowboy Bebop (1998)", source="provider"))
            session.add(ChannelDB(
                id="c5", source_id="c5", provider_id="p1",
                name="EN - Cowboy Bebop (1998)",
                detected_title="Cowboy Bebop", metadata_id="m5",
            ))

        _set_user_version(db, 3)
        db._clean_polluted_metadata_titles()   # runs, cleans to "Cowboy Bebop"
        db._clean_polluted_metadata_titles()   # version now 4 → fast-path return

        assert _metadata_title(db, "m5") == "Cowboy Bebop"


# ---------------------------------------------------------------------------
# Ingestion — ProviderMetadataProvider.get_details title resolution
# ---------------------------------------------------------------------------

class TestIngestionTitleResolution:
    def _provider(self, db):
        from metatv.metadata_providers.provider_metadata import ProviderMetadataProvider
        return ProviderMetadataProvider(db)

    def _add_channel(self, db, *, cid, name, detected_title, raw_data):
        with db.session_scope() as session:
            session.add(ChannelDB(
                id=cid, source_id=cid, provider_id="p1",
                name=name, media_type="movie",
                detected_title=detected_title, raw_data=raw_data,
            ))

    def test_absent_provider_name_uses_clean_detected_title(self, tmp_path):
        """No info.name → store the clean detected_title, not the raw channel name."""
        db = _make_db(tmp_path)
        self._add_channel(
            db, cid="c1",
            name="EN - Cowboy Bebop (1998)",
            detected_title="Cowboy Bebop",
            raw_data={"info": {"plot": "A ragtag crew of bounty hunters."}},
        )
        result = asyncio.run(self._provider(db).get_details("c1", media_type="movie"))

        assert result is not None and result.title == "Cowboy Bebop", (
            "Ingestion must fall back to the clean detected_title, never the raw name"
        )

    def test_raw_name_echoed_by_provider_uses_clean_detected_title(self, tmp_path):
        """info.name == raw channel name → still store the clean detected_title."""
        db = _make_db(tmp_path)
        self._add_channel(
            db, cid="c2",
            name="EN - Cowboy Bebop (1998)",
            detected_title="Cowboy Bebop",
            raw_data={"info": {"name": "EN - Cowboy Bebop (1998)", "plot": "x"}},
        )
        result = asyncio.run(self._provider(db).get_details("c2", media_type="movie"))

        assert result is not None and result.title == "Cowboy Bebop", (
            "A provider that only echoes the raw channel name must not repollute the title"
        )

    def test_real_distinct_provider_name_is_honored(self, tmp_path):
        """A genuine, distinct info.name overrides detected_title."""
        db = _make_db(tmp_path)
        self._add_channel(
            db, cid="c3",
            name="EN - Cowboy Bebop (1998)",
            detected_title="Cowboy Bebop",
            raw_data={"info": {"name": "Cowboy Bebop: The Movie", "plot": "x"}},
        )
        result = asyncio.run(self._provider(db).get_details("c3", media_type="movie"))

        assert result is not None and result.title == "Cowboy Bebop: The Movie", (
            "A real, distinct provider title must be preserved"
        )

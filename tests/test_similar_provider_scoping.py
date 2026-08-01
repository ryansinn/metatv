"""Similar Titles must never surface content from disabled/expired sources (absolute gate).

Bug: "Similar Titles" (both the details-pane row and the similar-titles lightbox) filtered
only ``ChannelDB.is_hidden`` and never excluded hidden providers, so a title-matching row on
a disabled/expired source — whose own ``is_hidden`` is 0 (a disabled PROVIDER doesn't flag
per-channel hide; those are gated at query time via ``get_hidden_provider_ids()``) — leaked
into the Similar row. That violates the active-source absolute gate (DR-0007).

Fix + standardization: both surfaces now route through ONE canonical chokepoint,
``ChannelRepository.get_similar_channels``, which owns the full visibility predicate
(``is_hidden`` AND ``~provider_id.in_(excluded_provider_ids)``). This suite proves:

  1. The chokepoint excludes disabled- and expired-provider matches while keeping the
     active-provider match — and would return the hidden ones if the gate were absent
     (the exact regression the old hand-rolled queries had).
  2. The details surface (``_MetadataMixin._bg_fetch_similar_titles``) excludes them.
  3. The lightbox surface (``SimilarTitleLightbox._bg_load``) excludes them.
  4. Neither surface still hand-rolls its own candidate query — both call the chokepoint
     (single source of truth), and the chokepoint carries both halves of the gate.

All DB tests use a file-backed tmp_path SQLite (not :memory:).
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _fake_config():
    """Minimal duck-typed Config for ``preference_engine.version_score``."""
    return SimpleNamespace(
        preferred_version_prefixes=[],
        preferred_version_provider_ids=[],
        preferred_version_quality=None,
    )


def _make_provider(session, pid: str, *, is_active: bool = True, exp=None):
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active, account_exp_date=exp,
    ))
    session.flush()


def _make_channel(session, *, cid: str, name: str, provider_id: str,
                  content_key: str, media_type: str = "movie",
                  is_hidden: bool = False):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        content_key=content_key,
        is_hidden=is_hidden,
    )
    session.add(ch)
    session.flush()
    return ch


def _seed(session):
    """Origin (active) + one title-matching sibling on each of active/disabled/expired.

    Every sibling has ``is_hidden=0`` and shares the origin's overlap words but a
    *distinct* content_key/title (so it reads as "similar", not an "other version").
    Only the disabled/expired providers gate their channels out.
    """
    now = datetime.now()
    _make_provider(session, "prov-active", is_active=True, exp=now + timedelta(days=30))
    _make_provider(session, "prov-disabled", is_active=False, exp=now + timedelta(days=30))
    _make_provider(session, "prov-expired", is_active=True, exp=now - timedelta(days=1))

    _make_channel(session, cid="ch-origin", name="Twelve Monkeys Origin",
                  provider_id="prov-active", content_key="origin|movie")
    _make_channel(session, cid="ch-active", name="Twelve Monkeys Returns",
                  provider_id="prov-active", content_key="returns|movie")
    _make_channel(session, cid="ch-disabled", name="Twelve Monkeys Disabled",
                  provider_id="prov-disabled", content_key="disabled|movie")
    _make_channel(session, cid="ch-expired", name="Twelve Monkeys Expired",
                  provider_id="prov-expired", content_key="expired|movie")


# ---------------------------------------------------------------------------
# 1. The canonical chokepoint
# ---------------------------------------------------------------------------

class TestChokepointProviderScoping:
    def test_excludes_disabled_and_expired_keeps_active(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory

        db = _make_db(tmp_path / "sim_scope.db")
        with db.session_scope() as session:
            _seed(session)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            excluded = set(repos.providers.get_hidden_provider_ids())
            # Sanity: both hidden providers are in the exclusion set; the active one isn't.
            assert "prov-disabled" in excluded and "prov-expired" in excluded
            assert "prov-active" not in excluded

            rows = repos.channels.get_similar_channels(
                "ch-origin", excluded_provider_ids=excluded, limit=20,
                config=_fake_config(),
            )
            ids = {r.id for r in rows}

        assert "ch-active" in ids, "an active-source similar title must appear"
        assert "ch-disabled" not in ids, "disabled-source content must never surface in Similar"
        assert "ch-expired" not in ids, "expired-source content must never surface in Similar"
        db.close()

    def test_without_gate_hidden_rows_would_leak(self, tmp_path):
        """Contrast — the exact regression: with no exclusion set (the old behavior) the
        disabled/expired rows DO match the heuristic, so it is the provider gate, not the
        query shape, that removes them."""
        from metatv.core.repositories import RepositoryFactory

        db = _make_db(tmp_path / "sim_noscope.db")
        with db.session_scope() as session:
            _seed(session)

        with db.session_scope(commit=False) as session:
            rows = RepositoryFactory(session).channels.get_similar_channels(
                "ch-origin", excluded_provider_ids=None, limit=20, config=_fake_config(),
            )
            ids = {r.id for r in rows}

        assert {"ch-active", "ch-disabled", "ch-expired"} <= ids, (
            f"without the gate every title-matching sibling matches; got {ids}"
        )
        db.close()


# ---------------------------------------------------------------------------
# 2. Details surface — _MetadataMixin._bg_fetch_similar_titles
# ---------------------------------------------------------------------------

class TestDetailsSurfaceScoping:
    def _make_mixin(self, db):
        from metatv.gui.main_window_metadata import _MetadataMixin

        emitted: list[tuple] = []

        class _FakeSignal:
            def emit(self, cid, titles):
                emitted.append((cid, titles))

        obj = _MetadataMixin.__new__(_MetadataMixin)
        obj.db = db
        obj.config = _fake_config()
        obj._similar_titles_loaded = _FakeSignal()
        obj._emitted = emitted
        return obj

    def test_details_similar_excludes_hidden_providers(self, tmp_path):
        db = _make_db(tmp_path / "sim_details.db")
        with db.session_scope() as session:
            _seed(session)

        obj = self._make_mixin(db)
        obj._bg_fetch_similar_titles("ch-origin")
        assert obj._emitted, "no similar-titles signal emitted"
        _, titles = obj._emitted[0]
        ids = {v.channel_id for v in titles}

        assert "ch-active" in ids
        assert "ch-disabled" not in ids and "ch-expired" not in ids, (
            f"details Similar row leaked hidden-source content: {ids}"
        )
        db.close()


# ---------------------------------------------------------------------------
# 3. Lightbox surface — SimilarTitleLightbox._bg_load
# ---------------------------------------------------------------------------

class TestLightboxSurfaceScoping:
    def test_lightbox_similar_excludes_hidden_providers(self, tmp_path):
        from metatv.gui.similar_lightbox import SimilarTitleLightbox

        db = _make_db(tmp_path / "sim_lightbox.db")
        with db.session_scope() as session:
            _seed(session)

        calls: list[tuple] = []

        class _FakeSignal:
            def emit(self, cid, data):
                calls.append((cid, data))

        # __new__ avoids building the Qt widget tree; _bg_load only touches
        # _db / _config / _data_ready.
        lb = SimilarTitleLightbox.__new__(SimilarTitleLightbox)
        lb._db = db
        lb._config = _fake_config()
        lb._data_ready = _FakeSignal()

        lb._bg_load("ch-origin")
        assert calls, "lightbox emitted no data"
        _, data = calls[0]
        sim_ids = {s["id"] for s in (data.get("similar") or [])}

        assert "ch-active" in sim_ids
        assert "ch-disabled" not in sim_ids and "ch-expired" not in sim_ids, (
            f"lightbox Similar list leaked hidden-source content: {sim_ids}"
        )
        db.close()


# ---------------------------------------------------------------------------
# 4. Consolidation — both surfaces call the single chokepoint (no duplicate query)
# ---------------------------------------------------------------------------

class TestConsolidatedChokepoint:
    def test_both_surfaces_call_get_similar_channels(self):
        from metatv.gui.main_window_metadata import _MetadataMixin
        from metatv.gui.similar_lightbox import SimilarTitleLightbox

        details_src = inspect.getsource(_MetadataMixin._bg_fetch_similar_titles)
        lightbox_src = inspect.getsource(SimilarTitleLightbox._bg_load)

        for label, src in (("details", details_src), ("lightbox", lightbox_src)):
            assert "get_similar_channels" in src, (
                f"{label} surface must route through the shared chokepoint"
            )
            # The old hand-rolled candidate query used an ``ilike`` scan; it must be gone.
            assert "ilike" not in src, (
                f"{label} surface still hand-rolls a candidate query (found ilike)"
            )

    def test_chokepoint_owns_both_visibility_halves(self):
        from metatv.core.repositories.channel import ChannelRepository

        src = inspect.getsource(ChannelRepository.get_similar_channels)
        assert "is_hidden" in src, "chokepoint must gate per-channel is_hidden"
        assert "provider_id.in_" in src, "chokepoint must gate excluded providers"


# ---------------------------------------------------------------------------
# 5. Global Filter (Exclusions) — Similar honors the same blacklist Discover does
# ---------------------------------------------------------------------------
#
# Bug: Similar/Explore/lightbox showed content the user had globally excluded
# (Albanian/German/NL after setting exclusions). The chokepoint now applies the
# Global Filter prefix blacklist when a (non-paused) config is supplied.

def _filter_config(*, excluded_categories=None, excluded_prefixes=None,
                   include_uncategorized=True, paused=False):
    """A duck-typed Config carrying BOTH the version-score and Global-Filter fields."""
    return SimpleNamespace(
        preferred_version_prefixes=[],
        preferred_version_provider_ids=[],
        preferred_version_quality=None,
        global_filter_paused=paused,
        global_filter_excluded_categories=list(excluded_categories or []),
        global_filter_excluded_prefixes=list(excluded_prefixes or []),
        global_filter_include_uncategorized=include_uncategorized,
    )


def _seed_langs(session):
    """Origin (EN) + one EN similar, one DE similar, one untagged (no prefix) similar.

    All on one active provider, all is_hidden=0, distinct content_keys (so each is a
    genuine 'similar', not an 'other version') and each shares the origin's overlap
    words.  Only detected_prefix distinguishes them for the Global-Filter test."""
    from metatv.core.database import ChannelDB

    now = datetime.now()
    _make_provider(session, "prov-active", is_active=True, exp=now + timedelta(days=30))

    def _ch(cid, name, prefix, ck):
        ch = ChannelDB(
            id=cid, source_id=str(uuid.uuid4()), provider_id="prov-active",
            name=name, media_type="movie", content_key=ck,
            is_hidden=False, detected_prefix=prefix,
        )
        session.add(ch)
        session.flush()

    _ch("o", "Twelve Monkeys Origin", "EN", "origin|movie")
    _ch("en-sim", "Twelve Monkeys English", "EN", "en|movie")
    _ch("de-sim", "Twelve Monkeys German", "DE", "de|movie")
    _ch("null-sim", "Twelve Monkeys Extra", None, "extra|movie")


def _similar_ids(db, config):
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope(commit=False) as session:
        rows = RepositoryFactory(session).channels.get_similar_channels(
            "o", excluded_provider_ids=None, limit=20, config=config,
        )
        return {r.id for r in rows}


class TestGlobalFilterExclusions:
    def test_excluded_category_drops_that_language(self, tmp_path):
        db = _make_db(tmp_path / "gf_cat.db")
        with db.session_scope() as session:
            _seed_langs(session)
        ids = _similar_ids(db, _filter_config(excluded_categories=["DE"]))
        assert "en-sim" in ids, "an un-excluded language similar stays"
        assert "null-sim" in ids, "untagged stays (include_uncategorized default True)"
        assert "de-sim" not in ids, "a globally-excluded language must be dropped"
        db.close()

    def test_block_prefix_drops_that_language(self, tmp_path):
        db = _make_db(tmp_path / "gf_pref.db")
        with db.session_scope() as session:
            _seed_langs(session)
        ids = _similar_ids(db, _filter_config(excluded_prefixes=["DE"]))
        assert "en-sim" in ids and "null-sim" in ids
        assert "de-sim" not in ids, "explicit Block [PREFIX] also drops it"
        db.close()

    def test_paused_config_applies_nothing(self, tmp_path):
        db = _make_db(tmp_path / "gf_paused.db")
        with db.session_scope() as session:
            _seed_langs(session)
        ids = _similar_ids(
            db, _filter_config(excluded_categories=["DE"], paused=True)
        )
        assert {"en-sim", "de-sim", "null-sim"} <= ids, "paused → excluded titles return"
        db.close()

    def test_config_none_applies_nothing(self, tmp_path):
        db = _make_db(tmp_path / "gf_none.db")
        with db.session_scope() as session:
            _seed_langs(session)
        ids = _similar_ids(db, None)
        assert {"en-sim", "de-sim", "null-sim"} <= ids, "config=None → no filter"
        db.close()

    def test_include_uncategorized_false_drops_untagged(self, tmp_path):
        db = _make_db(tmp_path / "gf_uncat.db")
        with db.session_scope() as session:
            _seed_langs(session)
        # Untagged (NULL prefix) visible with include_uncategorized True (default)...
        ids_show = _similar_ids(db, _filter_config(excluded_categories=["DE"]))
        assert "null-sim" in ids_show
        # ...but hidden when include_uncategorized is False.
        ids_hide = _similar_ids(
            db, _filter_config(excluded_categories=["DE"], include_uncategorized=False)
        )
        assert "null-sim" not in ids_hide, "untagged dropped when include_uncategorized False"
        assert "en-sim" in ids_hide, "a tagged, un-excluded language still shows"
        assert "de-sim" not in ids_hide
        db.close()


def test_whats_new_entry_180_present_with_test_steps():
    """Similar Titles honoring the Global Filter (Part D)."""
    from metatv.whats_new import WHATS_NEW
    entry = next((e for e in WHATS_NEW if e.id == 180), None)
    assert entry is not None, "What's New entry id=180 must be registered"
    assert entry.version == "0.15.0"
    assert entry.date == "2026-07-31"
    assert entry.items and entry.test_steps

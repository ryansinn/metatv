"""Behavioral tests for AI-provenance tagging (``(AI Generated)`` / ``(AI)``).

Covers the full chokepoint chain for the two AI-provenance markers:

1. The recognizer (``channel_name_utils.detect_ai_provenance``) — a unit matrix
   over both flavors, case/spelling variants, the Lektor-context confidence rule,
   and the deliberate NON-matches (mid-title parens, bare "AI", "(AIR)", …).
2. The decomposer (``tag_decomposer.decompose_ai_provenance``) — promotes the
   marker to a ``content_type`` facet tag.
3. Ingestion (``update_detected_prefixes`` + the ``TagBackfillTask`` tag builder)
   — proves the STORED ``content_type`` tag, the cleaned/retained
   ``detected_title``, the cleared bogus ``region="AI"``, and the content_key
   distinctness decision (voiceover collapses, ai_generated stays distinct).
4. The backfill — a pre-existing row gains the ``content_type`` tag after the
   version bump; a user tag survives (non-destructive).
5. The exclusion path — a channel tagged ``content_type:ai_generated`` disappears
   from ``get_channel_ids_by_tag_facets`` when that facet value is excluded.

All DB tests use a file-backed (``tmp_path``) SQLite DB per the CLAUDE.md rule
(not ``:memory:``, whose pooled connections each get an empty schema).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.channel_name_utils import (
    AI_GENERATED_VALUE,
    AI_VOICEOVER_VALUE,
    CONF_DENOTED,
    CONF_STRONG_PRIOR,
    detect_ai_provenance,
)


# ---------------------------------------------------------------------------
# 1. Recognizer unit matrix — detect_ai_provenance (pure, no DB)
# ---------------------------------------------------------------------------


class TestDetectAiProvenanceContent:
    """The ``(AI Generated)`` content marker → ai_generated, CONF_DENOTED."""

    @pytest.mark.parametrize(
        "name, cleaned",
        [
            (
                "[MV] Lady Gaga - Born To Win - ft. Sia & The Weeknd (AI Generated)",
                "[MV] Lady Gaga - Born To Win - ft. Sia & The Weeknd",
            ),
            ("Lady Gaga - I'll Survive (AI Generated)", "Lady Gaga - I'll Survive"),
            # Defensive spellings.
            ("Foo Bar (AI-Generated)", "Foo Bar"),
            ("Foo Bar (A.I. Generated)", "Foo Bar"),
            # Case-insensitive + inner padding.
            ("Foo Bar (ai generated)", "Foo Bar"),
            ("Foo Bar ( AI  Generated )", "Foo Bar"),
        ],
    )
    def test_matches_content_marker(self, name, cleaned):
        prov = detect_ai_provenance(name)
        assert prov is not None
        assert prov.value == AI_GENERATED_VALUE
        assert prov.confidence == CONF_DENOTED
        assert prov.cleaned_name == cleaned


class TestDetectAiProvenanceVoiceover:
    """The bare ``(AI)`` voiceover marker → ai_voiceover; Lektor drives confidence."""

    def test_bare_ai_is_low_confidence_voiceover(self):
        prov = detect_ai_provenance("PL - DOM MODY (AI)")
        assert prov is not None
        assert prov.value == AI_VOICEOVER_VALUE
        # No Lektor context → still the voiceover value, but ranked lower.
        assert prov.confidence == CONF_STRONG_PRIOR
        assert prov.cleaned_name == "PL - DOM MODY"

    def test_lektor_context_is_high_confidence(self):
        prov = detect_ai_provenance("PL - Bugonia (2025) Lektor (AI)")
        assert prov is not None
        assert prov.value == AI_VOICEOVER_VALUE
        # "Lektor" immediately before the marker → high confidence.
        assert prov.confidence == CONF_DENOTED
        assert prov.cleaned_name == "PL - Bugonia (2025) Lektor"

    def test_lektor_context_is_case_insensitive(self):
        prov = detect_ai_provenance("PL - Some Movie LEKTOR (ai)")
        assert prov is not None
        assert prov.value == AI_VOICEOVER_VALUE
        assert prov.confidence == CONF_DENOTED


class TestDetectAiProvenanceNonMatches:
    """The recognizer must never fire on these — no false positives."""

    @pytest.mark.parametrize(
        "name",
        [
            "AI Superstars",              # bare "AI", no parens
            "Weird AI Documentary",       # bare "AI" mid-name
            "Terminator (AI Uprising)",   # trailing parens, but not the marker
            "The Weird (AIR)",            # "(AIR)" != "(AI)"
            "Foo (AI) Bar",               # "(AI)" mid-title, not trailing
            "Foo (AI Generated) Bar",     # "(AI Generated)" mid-title, not trailing
            "Documentary about A.I.",     # no parens
            "Some Movie (2024)",          # trailing year, not AI
            "(AI) Leading Marker",        # leading, not trailing
            "",                           # empty
        ],
    )
    def test_non_match_returns_none(self, name):
        assert detect_ai_provenance(name) is None


# ---------------------------------------------------------------------------
# 2. Decomposer — decompose_ai_provenance emits the content_type triple
# ---------------------------------------------------------------------------


class TestDecomposeAiProvenance:
    def test_content_marker_emits_content_type_tag(self):
        from metatv.core.tag_decomposer import decompose_ai_provenance

        tags = decompose_ai_provenance("Lady Gaga - I'll Survive (AI Generated)")
        assert tags == [("content_type", AI_GENERATED_VALUE, CONF_DENOTED)]

    def test_voiceover_marker_emits_content_type_tag(self):
        from metatv.core.tag_decomposer import decompose_ai_provenance

        tags = decompose_ai_provenance("PL - DOM MODY (AI)")
        assert tags == [("content_type", AI_VOICEOVER_VALUE, CONF_STRONG_PRIOR)]

    def test_no_marker_emits_nothing(self):
        from metatv.core.tag_decomposer import decompose_ai_provenance

        assert decompose_ai_provenance("Plain Movie (2024)") == []


# ---------------------------------------------------------------------------
# Shared DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_db(tmp_path: Path):
    """File-backed SQLite Database with all tables created."""
    from metatv.core.database import Database
    from metatv.core.repositories.tag import _clear_tag_cache

    _clear_tag_cache()  # a fresh DB has its own tag-id space
    db_file = tmp_path / "test_ai_provenance.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()
    _clear_tag_cache()


@pytest.fixture
def cfg(tmp_path):
    """Isolated Config (config_dir on tmp_path — never the real ~/.config)."""
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


def _add_channel(session, name: str, media_type: str = "movie") -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id="p1",
            name=name,
            media_type=media_type,
        )
    )
    session.flush()
    return cid


# ---------------------------------------------------------------------------
# 3. Ingestion — stored content_type tag + cleaned/retained detected_title
# ---------------------------------------------------------------------------


class TestIngestion:
    """update_detected_prefixes + the tag builder over realistic corpus names."""

    def test_ai_generated_row_tagged_title_retained_key_distinct(self, file_db, cfg):
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.migrations.tag_backfill import TagBackfillTask

        with file_db.session_scope() as session:
            ai_id = _add_channel(
                session,
                "[MV] Lady Gaga - Born To Win - ft. Sia & The Weeknd (AI Generated)",
            )
            # A genuine same-base-title work — must NOT share the AI row's key.
            real_id = _add_channel(
                session, "Lady Gaga - Born To Win - ft. Sia & The Weeknd"
            )

        with file_db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes(config=cfg)

        TagBackfillTask(file_db, config=cfg).run(lambda d, t: None, lambda: False)

        with file_db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            ai = session.query(ChannelDB).filter_by(id=ai_id).one()
            real = session.query(ChannelDB).filter_by(id=real_id).one()
            ai_tags = set(repos.tags.tags_for(ai_id))
            real_tags = set(repos.tags.tags_for(real_id))
            ai_title = ai.detected_title
            ai_key, real_key = ai.content_key, real.content_key

        # The stored content_type tag lands.
        assert ("content_type", AI_GENERATED_VALUE) in ai_tags
        assert ("content_type", AI_GENERATED_VALUE) not in real_tags
        # ai_generated deliberately RETAINS its marker so identity stays distinct.
        assert "(AI Generated)" in ai_title
        assert ai_key != real_key, "AI-generated fake must not share a real work's content_key"

    def test_ai_voiceover_row_tagged_title_cleaned_region_not_ai(self, file_db, cfg):
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.migrations.tag_backfill import TagBackfillTask

        with file_db.session_scope() as session:
            lektor_id = _add_channel(session, "PL - Bugonia (2025) Lektor (AI)")
            bare_id = _add_channel(session, "PL - DOM MODY (AI)")

        with file_db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes(config=cfg)

        TagBackfillTask(file_db, config=cfg).run(lambda d, t: None, lambda: False)

        with file_db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            lektor = session.query(ChannelDB).filter_by(id=lektor_id).one()
            bare = session.query(ChannelDB).filter_by(id=bare_id).one()
            lektor_tags = set(repos.tags.tags_for(lektor_id))
            bare_tags = set(repos.tags.tags_for(bare_id))
            lektor_title, lektor_region = lektor.detected_title, lektor.detected_region
            bare_title, bare_region = bare.detected_title, bare.detected_region

        assert ("content_type", AI_VOICEOVER_VALUE) in lektor_tags
        assert ("content_type", AI_VOICEOVER_VALUE) in bare_tags
        # Voiceover marker is stripped from the display title (collapse-friendly).
        assert "(AI)" not in (lektor_title or "")
        assert "(AI)" not in (bare_title or "")
        # The "(AI)" marker must never masquerade as a locale (AI = Anguilla ISO).
        assert lektor_region != "AI"
        assert bare_region != "AI"
        # No bogus region facet leaked for either row.
        assert not any(v == "AI" for (t, v) in lektor_tags if t == "region")


# ---------------------------------------------------------------------------
# 4. Backfill — version bump re-tags existing rows; user tags survive
# ---------------------------------------------------------------------------


class TestBackfill:
    def test_needs_run_gates_on_version(self, file_db, cfg):
        from metatv.core.migrations.tag_backfill import (
            CURRENT_TAG_BACKFILL_VERSION,
            TagBackfillTask,
        )

        task = TagBackfillTask(file_db, config=cfg)
        cfg.tag_backfill_version = CURRENT_TAG_BACKFILL_VERSION - 1
        assert task.needs_run(cfg) is True
        task.on_completed(cfg)
        assert cfg.tag_backfill_version == CURRENT_TAG_BACKFILL_VERSION
        assert task.needs_run(cfg) is False

    def test_existing_row_gains_content_type_tag_after_backfill(self, file_db, cfg):
        """A pre-existing row (no AI tag yet) gains it when the backfill re-runs."""
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.migrations.tag_backfill import TagBackfillTask

        with file_db.session_scope() as session:
            cid = _add_channel(session, "Lady Gaga - I'll Survive (AI Generated)")

        # Simulate a stale install: no content_type tag exists yet.
        with file_db.session_scope(commit=False) as session:
            before = set(RepositoryFactory(session).tags.tags_for(cid))
        assert ("content_type", AI_GENERATED_VALUE) not in before

        # Bump behind current, then run the backfill (the on-launch re-tag path).
        cfg.tag_backfill_version = 0
        TagBackfillTask(file_db, config=cfg).run(lambda d, t: None, lambda: False)

        with file_db.session_scope(commit=False) as session:
            after = set(RepositoryFactory(session).tags.tags_for(cid))
        assert ("content_type", AI_GENERATED_VALUE) in after

    def test_backfill_preserves_user_tags(self, file_db, cfg):
        """The re-tag deletes only source='generated' rows — user tags survive."""
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.migrations.tag_backfill import TagBackfillTask

        with file_db.session_scope() as session:
            cid = _add_channel(session, "PL - DOM MODY (AI)")
            RepositoryFactory(session).tags.set_content_tags(
                cid, [("collection", "My Picks", "user")], source="user"
            )

        TagBackfillTask(file_db, config=cfg).run(lambda d, t: None, lambda: False)

        with file_db.session_scope(commit=False) as session:
            tags = set(RepositoryFactory(session).tags.tags_for(cid))
        assert ("collection", "My Picks") in tags, "user tag must survive re-tag"
        assert ("content_type", AI_VOICEOVER_VALUE) in tags, "generated AI tag added"


# ---------------------------------------------------------------------------
# 5. Exclusion path — the excludable facet actually hides the content
# ---------------------------------------------------------------------------


class TestExclusionPath:
    def test_excluding_ai_generated_hides_only_that_channel(self, file_db):
        """content_type:ai_generated exclusion drops the AI row via the real query path."""
        from metatv.core.repositories import RepositoryFactory

        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            ai_id = _add_channel(session, "Fake Song (AI Generated)")
            repos.tags.set_content_tags(
                ai_id, [("content_type", AI_GENERATED_VALUE, "name_ai_marker")]
            )
            plain_id = _add_channel(session, "Real Song")
            repos.tags.set_content_tags(
                plain_id, [("genre", "Pop", "test_feeder")]
            )

        # Baseline: no exclusion → both visible.
        with file_db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            everything = repos.tags.get_channel_ids_by_tag_facets({}, None)
        assert ai_id in everything and plain_id in everything

        # Exclude the facet value → the AI channel disappears; the plain one stays.
        with file_db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            remaining = repos.tags.get_channel_ids_by_tag_facets(
                {}, {"content_type": {AI_GENERATED_VALUE}}
            )
        assert ai_id not in remaining, "excluded ai_generated channel must disappear"
        assert plain_id in remaining, "untagged/other content must remain visible"

    def test_exclude_ai_generated_keeps_ai_voiceover(self, file_db):
        """Excluding AI content must NOT hide AI voiceovers — distinct facet values."""
        from metatv.core.repositories import RepositoryFactory

        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            gen_id = _add_channel(session, "Fake Song (AI Generated)")
            repos.tags.set_content_tags(
                gen_id, [("content_type", AI_GENERATED_VALUE, "name_ai_marker")]
            )
            dub_id = _add_channel(session, "PL - Bugonia Lektor (AI)")
            repos.tags.set_content_tags(
                dub_id, [("content_type", AI_VOICEOVER_VALUE, "name_ai_marker")]
            )

        with file_db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            remaining = repos.tags.get_channel_ids_by_tag_facets(
                {}, {"content_type": {AI_GENERATED_VALUE}}
            )
        assert gen_id not in remaining
        assert dub_id in remaining, "an AI voiceover must survive an AI-content exclusion"

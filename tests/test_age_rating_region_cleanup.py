"""An age rating is not a locale claim (REGION-1, owner report 2026-09-08).

``18+ - Truly Naked (2026)`` — category ``RATED R``, English audio, fr/fa/nl
subtitles — came back with ``detected_region = "DE"`` and a ``language=German``
tag derived from it.

``parse_channel_name`` yields no usable region for that name, because ``18+`` is
an age RATING. The final ingestion pass then filled the empty region from the
most common region among the row's ``content_key`` siblings — two genuine
``DE - Truly Naked (2026)`` rows. Majority won, DE was stamped, "German"
followed.

The guard that should have caught it existed and was one concept short:
``_contradicts_own_locale`` refuses to fill a row carrying its OWN locale code
(``EN``, ``AR`` …), because an empty region there is a fact rather than a gap.
An age rating is not a locale code, so the row looked eligible — while saying
strictly less about place than ``EN`` does.

Measured on the owner's library before the fix: 312 age-rated rows correctly
empty, **154 carrying an inherited region** (DE 40, PL 26, FR 17, ES 12, ALB 10,
IT 6, IN 6, …) — "A Serbian Film", "Benedetta (FRENCH MULTI SUB)" and "Bula
(TAGALOG ENG-SUB)" all filed as German.

Both halves are covered here: the forward fix (the fill is refused) and the
one-time cleanup (what is already stored is cleared, tags included). A row whose
own NAME carries a region — ``DE - …`` — must survive both untouched.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest

from metatv.core.channel_name_utils import AGE_RATING_PREFIXES

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture()
def db(tmp_path):
    """A real Database on a tmp_path FILE (project convention), one provider."""
    from metatv.core.database import Database, ProviderDB

    database = Database(f"sqlite:///{tmp_path}/age_rating_region.db")
    database.create_tables()
    with database.session_scope() as s:
        s.add(ProviderDB(
            id="p1", name="p1", type="xtream", url="http://x",
            urls='[{"url": "http://x", "primary": true}]',
            username="u", password="p", is_active=True,
        ))
    return database


def _add_raw(database, *, name, category="", prefix=None, region=None, key=None):
    """Insert a channel with the stored fields set explicitly."""
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    with database.session_scope() as s:
        s.add(ChannelDB(
            id=cid, provider_id="p1", name=name, source_id=cid,
            media_type="movie", category=category,
            detected_prefix=prefix, detected_region=region, content_key=key,
        ))
    return cid


def _region_of(database, cid):
    from metatv.core.database import ChannelDB

    with database.session_scope() as s:
        return s.query(ChannelDB.detected_region).filter(
            ChannelDB.id == cid).scalar()


def _tags_of(database, cid):
    from metatv.core.database import ContentTagDB, TagDB

    with database.session_scope() as s:
        return {
            (t.type, t.value) for t in
            s.query(TagDB)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_id == cid).all()
        }


def _tag(database, cid, type_, value):
    from metatv.core.database import ContentTagDB, TagDB

    with database.session_scope() as s:
        existing = s.query(TagDB).filter(
            TagDB.type == type_, TagDB.value == value).first()
        if existing is None:
            existing = TagDB(type=type_, value=value)
            s.add(existing)
            s.flush()
        s.add(ContentTagDB(channel_id=cid, tag_id=existing.id, source="generated"))


def _run_migration(database):
    from metatv.core.migrations.age_rating_region_cleanup import (
        AgeRatingRegionCleanupTask,
    )

    AgeRatingRegionCleanupTask(database).run(lambda d, t: None, lambda: False)


# ---------------------------------------------------------------------------
# The forward fix: the sibling fill must refuse an age-rating row
# ---------------------------------------------------------------------------


class TestSiblingFill:

    def test_the_owner_reported_shape_end_to_end(self, db):
        """Two genuine DE rows, one 18+ row — the 18+ row must stay empty.

        Driven through ``update_detected_prefixes()``, the real ingestion
        chokepoint, so the sibling-propagation pass runs exactly as it does on a
        refresh. Fails against the pre-fix code, which stamps DE on the 18+ row.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        de1 = _add_raw(db, name="DE - Truly Naked (2026)", category="DE| RATED R")
        de2 = _add_raw(db, name="DE - Truly Naked (2026) 4K", category="DE| RATED R")
        rated = _add_raw(db, name="18+ - Truly Naked (2026)", category="RATED R")
        english = _add_raw(db, name="EN - Truly Naked (2026)", category="RATED R")

        with db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes(
                provider_id=None
            )

        with db.session_scope() as s:
            keys = {
                row.id: row.content_key
                for row in s.query(ChannelDB).all()
            }
        assert len(set(keys.values())) == 1, (
            "the four rows must share one content_key, or the propagation this "
            "test exercises never engages"
        )

        assert _region_of(db, rated) in (None, ""), (
            f"the 18+ row inherited {_region_of(db, rated)!r} — an age rating "
            f"says what may be watched, never where"
        )
        assert _region_of(db, english) in (None, ""), (
            "the |EN| case must not regress — it is why the guard exists"
        )
        assert _region_of(db, de1) == "DE"
        assert _region_of(db, de2) == "DE", (
            "a row whose own category/name carries DE keeps DE — the fix must "
            "not clear real information"
        )

    def test_a_prefix_with_no_locale_still_inherits(self, db):
        """Do not over-correct: MULTI/4K rows are what propagation is FOR."""
        from metatv.core.repositories import RepositoryFactory

        key = "sometitle|movie|2020"
        _add_raw(db, name="DE - X", prefix="DE", region="DE", key=key)
        _add_raw(db, name="DE - X 4K", prefix="DE", region="DE", key=key)
        multi = _add_raw(db, name="MULTI - X", prefix="MULTI", region="", key=key)
        rated = _add_raw(db, name="18+ - X", prefix="18+", region="", key=key)

        with db.session_scope() as session:
            RepositoryFactory(session).channels._propagate_region_from_siblings_impl()

        assert _region_of(db, multi) == "DE", (
            "MULTI has no locale of its own, so it SHOULD still inherit — the "
            "fix must not disable propagation wholesale"
        )
        assert _region_of(db, rated) in (None, "")

    @pytest.mark.parametrize("rating", sorted(AGE_RATING_PREFIXES))
    def test_every_age_rating_blocks_the_fill(self, rating):
        """Every member of the curated set, not just the one the owner hit."""
        from metatv.core.repositories.channel_ingestion import (
            _contradicts_own_locale,
        )

        assert _contradicts_own_locale(rating, "DE") is True

    @pytest.mark.parametrize("own_prefix,candidate,expected", [
        ("EN", "DE", True),      # the pre-existing case — must not regress
        ("AR", "DE", True),
        ("IT", "IT", False),     # sibling agrees with the row's own code
        ("MULTI", "DE", False),  # no locale of its own — inheriting is intended
        ("4K", "DE", False),
        (None, "DE", False),
    ])
    def test_the_existing_predicate_cases_are_unchanged(
        self, own_prefix, candidate, expected
    ):
        from metatv.core.repositories.channel_ingestion import (
            _contradicts_own_locale,
        )

        assert _contradicts_own_locale(own_prefix, candidate) is expected


# ---------------------------------------------------------------------------
# The cleanup: a re-parse cannot undo a stored fill
# ---------------------------------------------------------------------------


class TestMigration:

    def test_clears_the_stored_region_and_the_tags_derived_from_it(self, db):
        """The visible symptom, not just the column.

        The region produced a ``region`` facet the user can filter by AND the
        ``language`` facet that region implies, which is what made an English
        film read as German everywhere.
        """
        cid = _add_raw(db, name="18+ - A Serbian Film (2010)", category="RATED R",
                       prefix="18+", region="DE")
        _tag(db, cid, "region", "DE")
        _tag(db, cid, "language", "German")
        _tag(db, cid, "genre", "Drama")

        _run_migration(db)

        assert _region_of(db, cid) in (None, "")
        remaining = _tags_of(db, cid)
        assert ("region", "DE") not in remaining, "the bogus region tag survived"
        assert ("language", "German") not in remaining, (
            "the language tag derived from the bogus region survived — the "
            "title still reads German in filters and recommendations"
        )
        assert ("genre", "Drama") in remaining, (
            "only the region-derived facets go; unrelated tags must stay"
        )

    def test_a_name_carried_region_is_untouched(self, db):
        """``DE - Truly Naked (2026)`` states DE itself and keeps it."""
        cid = _add_raw(db, name="DE - Truly Naked (2026)", category="DE| RATED R",
                       prefix="DE", region="DE")
        _tag(db, cid, "region", "DE")
        _tag(db, cid, "language", "German")

        _run_migration(db)

        assert _region_of(db, cid) == "DE", (
            "the predicate is detected_prefix IS an age rating — a row whose own "
            "name carries DE is outside it and must keep its region"
        )
        assert _tags_of(db, cid) == {("region", "DE"), ("language", "German")}

    def test_an_empty_region_on_an_age_rating_row_is_left_alone(self, db):
        """312 of the owner's age-rated rows were already correct."""
        cid = _add_raw(db, name="18+ - Something (2020)", category="RATED R",
                       prefix="18+", region=None)

        _run_migration(db)

        assert _region_of(db, cid) in (None, "")

    def test_a_second_run_changes_nothing(self, db):
        """Only ever clears, so it converges — safe to retry after a crash."""
        cleared = _add_raw(db, name="18+ - X (2020)", prefix="18+", region="PL")
        kept = _add_raw(db, name="DE - X (2020)", prefix="DE", region="DE")
        _tag(db, kept, "region", "DE")

        _run_migration(db)
        first = (_region_of(db, cleared), _region_of(db, kept), _tags_of(db, kept))
        _run_migration(db)
        second = (_region_of(db, cleared), _region_of(db, kept), _tags_of(db, kept))

        assert first == second
        assert first[0] in (None, "")
        assert first[1] == "DE"

    def test_needs_run_respects_the_stored_version(self, tmp_path):
        from metatv.core.config import Config
        from metatv.core.migrations.age_rating_region_cleanup import (
            CURRENT_VERSION, AgeRatingRegionCleanupTask,
        )

        cfg = Config(config_dir=tmp_path / "cfg")
        task = AgeRatingRegionCleanupTask(None)
        assert task.needs_run(cfg) is True
        task.on_completed(cfg)
        assert cfg.age_rating_region_cleanup_version == CURRENT_VERSION
        assert task.needs_run(cfg) is False


# ---------------------------------------------------------------------------
# One definition, two readers
# ---------------------------------------------------------------------------


class TestOneDefinition:
    """``AGE_RATING_PREFIXES`` is the only place the ratings are enumerated.

    The tuple used to be inline in ``classify_trailing_metadata``, with the
    ingestion guard knowing nothing about it. A fourth rating added to one of
    them would have reached one reader and not the other — the "an enumeration
    never sees what nobody remembered to add" failure in miniature.
    """

    #: Derived, so a fourth rating added to the set is covered without anyone
    #: remembering to widen this test.
    RATINGS = AGE_RATING_PREFIXES

    @pytest.mark.parametrize("module_path", [
        "metatv/core/channel_name_utils.py",
        "metatv/core/repositories/channel_ingestion.py",
    ])
    def test_no_module_spells_a_rating_out_for_itself(self, module_path):
        """AST-based, so prose in a comment or docstring is fine — only real
        string constants in code count."""
        path = REPO_ROOT / module_path
        tree = ast.parse(path.read_text(encoding="utf-8"))

        offenders = []
        for node in ast.walk(tree):
            # The definition itself is the one allowed spelling.
            if (isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == "AGE_RATING_PREFIXES"):
                continue
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value in self.RATINGS):
                offenders.append(node.value)

        # The definition's own members are reachable by ast.walk from the module
        # root, so subtract exactly one occurrence of each.
        for member in sorted(self.RATINGS):
            if member in offenders:
                offenders.remove(member)

        assert not offenders, (
            f"{module_path} spells out {sorted(set(offenders))} instead of "
            f"reading AGE_RATING_PREFIXES — a fourth rating would reach one "
            f"reader and not the other"
        )

    def test_both_readers_answer_from_the_same_set(self):
        """Behavioural half: every member classifies AND blocks the fill."""
        from metatv.core.channel_name_utils import (
            AGE_RATING_PREFIXES, classify_trailing_metadata,
        )
        from metatv.core.repositories.channel_ingestion import (
            _contradicts_own_locale,
        )

        assert AGE_RATING_PREFIXES, "the set must not be empty"
        for rating in AGE_RATING_PREFIXES:
            assert classify_trailing_metadata(rating) == ("rating", rating)
            assert _contradicts_own_locale(rating, "DE") is True

    def test_the_parser_still_routes_an_age_rating_prefix_to_region(self):
        """Step 7's behaviour is unchanged by the refactor — ``18+`` still lands
        in ``ParsedChannel.region`` (which ingestion reads as the PREFIX)."""
        from metatv.core.channel_name_utils import parse_channel_name

        parsed = parse_channel_name("18+ - Truly Naked (2026)")
        assert parsed.region == "18+"
        assert parsed.bare_name == "Truly Naked"
        assert parsed.quality == [], "an age rating is not a quality tier"

        four_k = parse_channel_name("4K - Truly Naked (2026)")
        assert four_k.quality == ["4K"], "a real quality prefix still lands there"
        assert four_k.region == ""

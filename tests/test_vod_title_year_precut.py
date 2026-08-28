"""Behavioral tests for the mid-name year pre-cut in parse_channel_name.

Movie channel names of the form ``Prefix - Title [4K] (Year) CAST/EXTRA`` used to
lose the year entirely (``_YEAR_RE`` is end-anchored) AND keep the whole trailing
cast/extra blob in ``detected_title``. The fix adds a small pre-cut step that
relocates a real ``(YYYY)``/``(YYYY-YYYY)`` that has trailing text after it so the
existing end-anchored steps (quality/audio/lang/year) extract it normally.

All DB tests use file-backed (tmp_path) SQLite — not :memory: — per CLAUDE.md rule.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(session, *, name: str, provider_id: str = "p1",
                   media_type: str = "movie") -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
    ))
    return cid


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables created."""
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'test_year_precut.db'}")
    d.create_tables()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# 1. parse_channel_name — mid-name year pre-cut
# ---------------------------------------------------------------------------


class TestMidNameYearPreCut:
    """A '(YYYY)' followed by trailing cast/extra credits is relocated so the
    existing end-anchored quality/year steps still extract it normally."""

    def _parse(self, name: str):
        from metatv.core.channel_name_utils import parse_channel_name
        return parse_channel_name(name)

    def test_from_dusk_till_dawn_cast_trailing(self):
        """'EN - From Dusk Till Dawn 4K (1996) HARVEY KEITEL, TARANTINO' → clean title + year."""
        r = self._parse(
            "EN - From Dusk Till Dawn 4K (1996) HARVEY KEITEL, TARANTINO"
        )
        assert r.bare_name == "From Dusk Till Dawn", (
            f"Expected 'From Dusk Till Dawn', got {r.bare_name!r}"
        )
        assert r.year == "1996", f"Expected year '1996', got {r.year!r}"
        assert "4K" in r.quality, f"Expected 4K quality captured, got {r.quality!r}"

    def test_all_the_presidents_men_cast_trailing(self):
        """'... All The President's Men (1976) DUSTIN HOFFMAN, ROBERT REDFORD' → clean title + year."""
        r = self._parse(
            "EN - All The President's Men (1976) DUSTIN HOFFMAN, ROBERT REDFORD"
        )
        assert r.bare_name == "All The President's Men", (
            f"Expected \"All The President's Men\", got {r.bare_name!r}"
        )
        assert r.year == "1976", f"Expected year '1976', got {r.year!r}"

    def test_wicked_extra_trailing(self):
        """'Wicked (2024) BROADWAY MUSICAL' → title 'Wicked', year '2024'."""
        r = self._parse("EN - Wicked (2024) BROADWAY MUSICAL")
        assert r.bare_name == "Wicked", f"Expected 'Wicked', got {r.bare_name!r}"
        assert r.year == "2024", f"Expected year '2024', got {r.year!r}"

    def test_clean_year_no_trailing_text_unaffected(self):
        """Clean 'Foo (1999)' with nothing trailing still parses correctly (unaffected)."""
        r = self._parse("Foo (1999)")
        assert r.bare_name == "Foo"
        assert r.year == "1999"

    def test_directors_cut_not_a_year_preserved(self):
        """"Blade Runner (Director's Cut)" has no digit year — the pre-cut must not fire."""
        r = self._parse("Blade Runner (Director's Cut)")
        assert "(Director's Cut)" in r.bare_name, (
            f"'(Director's Cut)' must be preserved (not a year parenthetical); "
            f"got {r.bare_name!r}"
        )

    def test_bare_trailing_number_in_title_unchanged(self):
        """'Blade Runner 2049' — bare trailing number is part of the title, not a paren year."""
        r = self._parse("Blade Runner 2049")
        assert r.bare_name == "Blade Runner 2049"
        assert r.year == ""

    def test_space_1999_unchanged(self):
        """'Space 1999' — bare trailing number preserved."""
        r = self._parse("Space 1999")
        assert r.bare_name == "Space 1999"

    def test_the_4400_unchanged(self):
        """'The 4400' — bare trailing number preserved."""
        r = self._parse("The 4400")
        assert r.bare_name == "The 4400"

    def test_multiple_parenthesized_years_uses_last(self):
        """When multiple '(YYYY)' appear, the LAST one is the cut point."""
        r = self._parse("Foo (1990) Bar (1995) SOME CAST")
        assert r.bare_name == "Foo (1990) Bar", f"Got {r.bare_name!r}"
        assert r.year == "1995", f"Expected year '1995', got {r.year!r}"

    def test_title_case_trailing_text_preserved(self):
        """'FBI (2024) Reboot' — an UNRECOGNISED title-case trailer is a real
        subtitle, not a cast/extra blob, so the TEXT must survive in the name.

        The year no longer survives with it: it is unambiguous wherever it
        appears, so it is lifted into its own field while "Reboot" stays put.
        This asserts the property the guard exists for — the subtitle is not
        eaten — rather than the old exact string, which also encoded the year
        being stranded in the title (CLAUDE.md: don't pin what an improvement
        will move).  parse_platform_event's bare-year rejection is unaffected.
        """
        r = self._parse("FBI (2024) Reboot")
        assert "Reboot" in r.bare_name, f"subtitle eaten: {r.bare_name!r}"
        assert "(2024)" not in r.bare_name, f"year stranded: {r.bare_name!r}"
        assert r.year == "2024", f"Got {r.year!r}"
        assert r.trailing_meta is None, "unrecognised text must not be classified"
        assert r.trailing == "", "an unrecognised trailer is not a cast blob"

    def test_trailing_region_qualifier_after_year_preserved(self):
        """'4K-DE - Hanna (2019) (US)' — trailing (US) is a real qualifier, handled
        by the existing lang-qualifier step, not junk to relocate."""
        r = self._parse("4K-DE - Hanna (2019) (US)")
        assert r.bare_name == "Hanna", f"Got {r.bare_name!r}"
        assert r.year == "2019", f"Got {r.year!r}"
        assert r.lang == "US", f"Expected lang 'US', got {r.lang!r}"

    def test_year_range_with_trailing_text(self):
        """A year-range '(1993-2002)' with trailing text is also relocated."""
        r = self._parse("X-Files (1993-2002) DAVID DUCHOVNY, GILLIAN ANDERSON")
        assert r.bare_name == "X-Files", f"Expected 'X-Files', got {r.bare_name!r}"
        assert r.year == "1993-2002", f"Expected '1993-2002', got {r.year!r}"

    def test_hevc_before_year_unaffected(self):
        """Pre-existing docstring example: 'AR - Bob Marley: One Love HEVC (2024)'."""
        r = self._parse("AR - Bob Marley: One Love HEVC (2024)")
        assert r.bare_name == "Bob Marley: One Love"
        assert r.year == "2024"
        assert r.quality == ["HEVC"]


# ---------------------------------------------------------------------------
# 2. End-to-end via update_detected_prefixes — backfill correctness
# ---------------------------------------------------------------------------


def test_update_detected_prefixes_fixes_polluted_row(db):
    """A previously-polluted row (cast trailing the year) is corrected by a re-parse.

    Simulates the backfill: a channel row is inserted with the raw provider name
    that used to leave the cast blob in detected_title and an empty detected_year;
    after running update_detected_prefixes(), both are corrected.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="EN - From Dusk Till Dawn 4K (1996) HARVEY KEITEL , TARANTINO, CHEECH MARIN",
            media_type="movie",
        )

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        ch = session.query(ChannelDB).filter_by(id=cid).one()
        title = ch.detected_title
        year = ch.detected_year

    assert title == "From Dusk Till Dawn", (
        f"Expected clean detected_title 'From Dusk Till Dawn', got {title!r}"
    )
    assert year == "1996", f"Expected detected_year '1996', got {year!r}"


# ---------------------------------------------------------------------------
# 3. DetectedTitleReparseTask — version bump triggers the backfill re-run
# ---------------------------------------------------------------------------


def test_detected_title_reparse_version_bumped_for_precut_fix():
    """CURRENT_VERSION was bumped so existing installs re-run the backfill once."""
    from metatv.core.migrations.detected_title_reparse import CURRENT_VERSION

    assert CURRENT_VERSION >= 7, (
        "detected_title_reparse CURRENT_VERSION must be bumped so the mid-name "
        "year pre-cut fix backfills existing polluted rows on next launch."
    )


def test_detected_title_reparse_task_needs_run_with_stale_version(tmp_path: Path):
    """A config carrying an older reparse version is flagged as needing the re-run."""
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.migrations.detected_title_reparse import (
        DetectedTitleReparseTask,
        CURRENT_VERSION,
    )

    config = Config(config_dir=tmp_path / "config")
    config.detected_reparse_version = CURRENT_VERSION - 1
    config.save()

    d = Database(f"sqlite:///{tmp_path / 'stale_version.db'}")
    d.create_tables()

    task = DetectedTitleReparseTask(d)
    assert task.needs_run(config) is True, (
        "A config left on an older detected_reparse_version must trigger a re-run."
    )

    task.on_completed(config)
    assert task.needs_run(config) is False
    assert config.detected_reparse_version == CURRENT_VERSION

    d.close()


def test_reparse_task_backfills_polluted_row_end_to_end(tmp_path: Path):
    """DetectedTitleReparseTask.run() (the registered migration path) fixes a
    polluted row exactly like the direct update_detected_prefixes() call does —
    this is the actual backfill trigger a real install goes through on launch.
    """
    from metatv.core.database import ChannelDB, Database
    from metatv.core.migrations.detected_title_reparse import DetectedTitleReparseTask

    d = Database(f"sqlite:///{tmp_path / 'reparse_backfill.db'}")
    d.create_tables()

    with d.session_scope() as session:
        cid = _make_channel(
            session,
            name="EN - Wicked (2024) BROADWAY MUSICAL",
            media_type="movie",
        )

    task = DetectedTitleReparseTask(d)
    task.run(progress_cb=lambda done, total: None, is_cancelled=lambda: False)

    with d.session_scope(commit=False) as session:
        ch = session.query(ChannelDB).filter_by(id=cid).one()
        title = ch.detected_title
        year = ch.detected_year

    d.close()

    assert title == "Wicked", f"Expected 'Wicked', got {title!r}"
    assert year == "2024", f"Expected '2024', got {year!r}"


# ---------------------------------------------------------------------------
# The year always wins — trailing text no longer hides it (v10 re-parse)
# ---------------------------------------------------------------------------
#
# v7 relocated a mid-name "(YYYY)" only when the text after it was ALL-CAPS, on
# the theory that provider junk is uppercase and title-case is a real subtitle.
# Measured on the owner's library that was wrong for 2,092 rows across 478
# trailers: "sinhronizirano" (385), "Hallmark" (322), "Polski" (176) are all
# provider metadata in title case.  Those rows parsed with year="" and kept
# "(2021) Hallmark" inside detected_title, so they keyed to the coarse yearless
# content_key AND could not match their own siblings.


class TestYearAlwaysWins:
    """The year is unambiguous wherever it sits; only the trailing TEXT is judged."""

    @staticmethod
    def _p(name: str):
        from metatv.core.channel_name_utils import parse_channel_name
        return parse_channel_name(name)

    def test_the_owners_reported_row(self):
        """The reported case: 'EN - Christmas At Castle Hart (2021) Hallmark'."""
        r = self._p("EN - Christmas At Castle Hart (2021) Hallmark")
        assert r.bare_name == "Christmas At Castle Hart", f"Got {r.bare_name!r}"
        assert r.year == "2021", f"Got {r.year!r}"
        assert r.trailing_meta == ("collection", "Hallmark")

    def test_a_dub_marker_after_the_year_is_not_part_of_the_title(self):
        """'sinhronizirano' — 385 rows, the single most common trailer."""
        r = self._p("SI - Nekaj (2015) sinhronizirano")
        assert r.bare_name == "Nekaj", f"Got {r.bare_name!r}"
        assert r.year == "2015"
        assert r.trailing_meta == ("dub", "Slovenian")

    def test_a_self_labelling_collection_needs_no_curation(self):
        """'- Lucky Luke Collection' says what it is; no lookup entry required."""
        r = self._p("EN - Tale (2001) - Lucky Luke Collection")
        assert r.bare_name == "Tale", f"Got {r.bare_name!r}"
        assert r.trailing_meta == ("collection", "Lucky Luke")

    def test_dubbed_in_language_form(self):
        r = self._p("AL - Kino (2020) - Dubbed in Albanian")
        assert r.bare_name == "Kino"
        assert r.trailing_meta == ("dub", "Albanian")

    def test_a_year_range_with_a_recognised_trailer(self):
        r = self._p("EN - X-Files (1993-2002) Dubbing")
        assert r.bare_name == "X-Files", f"Got {r.bare_name!r}"
        assert r.year == "1993-2002", f"Got {r.year!r}"

    def test_an_all_caps_cast_blob_is_still_cast_not_metadata(self):
        """The v7 behaviour must be untouched — 0 cast blobs were lost."""
        r = self._p("EN - Film (1996) HARVEY KEITEL")
        assert r.bare_name == "Film"
        assert r.year == "1996"
        assert r.trailing == "HARVEY KEITEL"
        assert r.trailing_meta is None, "a cast blob is not classified metadata"

    def test_an_unrecognised_trailer_keeps_its_text_but_yields_the_year(self):
        """The conservative half: 383 of 478 trailers are singletons that may be
        real subtitles.  They keep their text; they still gain the year."""
        r = self._p("EN - Captains Of The World (2023) Lionel Messi")
        assert "Lionel Messi" in r.bare_name, f"Got {r.bare_name!r}"
        assert r.year == "2023", f"Got {r.year!r}"
        assert r.trailing_meta is None

    def test_a_plain_trailing_year_is_unchanged(self):
        r = self._p("EN - Normal Film (2019)")
        assert r.bare_name == "Normal Film"
        assert r.year == "2019"
        assert r.trailing_meta is None


class TestTrailingClassifier:
    """classify_trailing_metadata refuses to guess — that is what makes it safe."""

    @staticmethod
    def _c(text):
        from metatv.core.channel_name_utils import classify_trailing_metadata
        return classify_trailing_metadata(text)

    def test_unknown_text_is_not_classified(self):
        """The safety valve: an unnamed trailer must stay in the title."""
        for text in ("Reboot", "Lionel Messi", "The Beginning", ""):
            assert self._c(text) is None, f"{text!r} was wrongly classified"

    def test_each_recognised_family(self):
        assert self._c("Hallmark") == ("collection", "Hallmark")
        assert self._c("- Gullivers Collection") == ("collection", "Gullivers")
        assert self._c("Polski") == ("dub", "Polish")
        assert self._c("Napisy") == ("sub", "Polish")
        assert self._c("Dokument") == ("genre", "Documentary")
        assert self._c("18+") == ("rating", "18+")
        assert self._c("4k") == ("quality", "4K")


# ---------------------------------------------------------------------------
# The recognised collection is STORED and TAGGED — not just dropped
# ---------------------------------------------------------------------------
#
# Cleaning "(2021) Hallmark" out of the title is only half the job: without
# somewhere to put "Hallmark" the fix would trade a wrong title for a lost
# collection.  detected_collection already holds the cleaned PROVIDER CATEGORY
# ("CHRISTMAS"), a different feeder, so the name-derived one gets its own field
# beside detected_name_cast.  Both become collection: tags — the provider's
# denoted, this one at CONF_STRONG_PRIOR — which is what lets a single title
# belong to more than one collection at all.


class TestNameCollectionIsKept:

    def test_ingestion_stores_the_name_collection(self, db):
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            cid = _make_channel(
                session, name="EN - Christmas At Castle Hart (2021) Hallmark"
            )
        with db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes()
        with db.session_scope(commit=False) as session:
            ch = session.query(ChannelDB).filter_by(id=cid).one()
            assert ch.detected_title == "Christmas At Castle Hart"
            assert ch.detected_year == "2021"
            assert ch.detected_name_collection == "Hallmark", (
                f"collection lost: {ch.detected_name_collection!r}"
            )

    def test_the_provider_category_is_not_overwritten(self, db):
        """The multi-collection property: a title filed under CHRISTMAS whose
        name says Hallmark must end up carrying BOTH, not one replacing the other.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            cid = _make_channel(
                session, name="EN - A Carol Christmas (2003) Hallmark"
            )
            session.query(ChannelDB).filter_by(id=cid).one().category = "CHRISTMAS"

        with db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes()

        with db.session_scope(commit=False) as session:
            ch = session.query(ChannelDB).filter_by(id=cid).one()
            assert ch.detected_collection == "CHRISTMAS", (
                f"provider category clobbered: {ch.detected_collection!r}"
            )
            assert ch.detected_name_collection == "Hallmark"

    def test_an_unrecognised_trailer_stores_no_collection(self, db):
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            cid = _make_channel(session, name="EN - FBI (2024) Reboot")
        with db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes()
        with db.session_scope(commit=False) as session:
            ch = session.query(ChannelDB).filter_by(id=cid).one()
            assert ch.detected_name_collection is None
            assert ch.detected_year == "2024"

    def test_the_tag_layer_promotes_it_below_the_denoted_one(self):
        """Emitted at CONF_STRONG_PRIOR so it ranks under a provider category."""
        from metatv.core.channel_name_utils import CONF_DENOTED, CONF_STRONG_PRIOR
        from metatv.core.config import Config
        from metatv.core.tag_decomposer import decompose_name_parse

        tags = decompose_name_parse(
            detected_prefix="EN", detected_quality=None, detected_region=None,
            detected_year="2021", config=Config(),
            detected_name_collection="Hallmark",
        )
        coll = [t for t in tags if t[0] == "collection"]
        assert coll == [("collection", "Hallmark", CONF_STRONG_PRIOR)], coll
        assert CONF_STRONG_PRIOR < CONF_DENOTED, "must rank below a denoted category"

        without = decompose_name_parse(
            detected_prefix="EN", detected_quality=None, detected_region=None,
            detected_year="2021", config=Config(),
        )
        assert not [t for t in without if t[0] == "collection"]

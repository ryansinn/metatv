"""One-time sweep clearing regions nothing on the row supports (#275).

Owner: "is there going to be a fix for all these misrepresented [DE] region
series… clearly A+, D+ etc are mostly US, but better to have no region than lump
everything under Germany."

The forward fix (#272) is fill-empty-only, so it stops new mislabels and leaves
the existing ones. Measured on the owner's library: **78,327 rows** carrying a
region nothing on the row supports.

Two populations, two arbiters:

1. **Locale-prefixed rows** — the prefix is a recognised code and the region
   contradicts it (``|EN| Aladdin`` → DE, ``|AR| Aladdin`` → DE).
2. **Platform-prefixed rows** — ``A+``/``D+``/``NF`` are not locales, so nothing
   contradicts; the arbiter is whether the row's own CATEGORY implies the
   region. Real cases from the owner's library: ``D+`` under ``"UK| DISCOVERY +"``
   keeps UK, ``PRIME`` under ``"US| PRIME"`` keeps US, ``A+`` under
   ``"APPLE+ MOVIES"`` loses ISR/FR/NL.

The sweep only ever CLEARS. An empty region is honest; guessing a different
country would repeat the original mistake.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database, ProviderDB

    database = Database(f"sqlite:///{tmp_path}/region_cleanup.db")
    database.create_tables()
    with database.session_scope() as s:
        s.add(ProviderDB(
            id="p1", name="p1", type="xtream", url="http://x",
            urls='[{"url": "http://x", "primary": true}]',
            username="u", password="p", is_active=True,
        ))
    return database


def _add(database, *, prefix, region, category=""):
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    with database.session_scope() as s:
        s.add(ChannelDB(
            id=cid, provider_id="p1", name=f"|{prefix}| Thing", source_id=cid,
            media_type="movie", detected_prefix=prefix, detected_region=region,
            category=category,
        ))
    return cid


def _region_of(database, cid):
    from metatv.core.database import ChannelDB

    with database.session_scope() as s:
        return s.query(ChannelDB.detected_region).filter(ChannelDB.id == cid).scalar()


def _run(database):
    from metatv.core.migrations.bad_region_cleanup import BadRegionCleanupTask

    BadRegionCleanupTask(database).run(lambda d, t: None, lambda: False)


class TestLocaleContradictions:

    def test_clears_a_contradicting_region(self, db):
        """The owner's case: |EN| row stamped DE."""
        cid = _add(db, prefix="EN", region="DE")
        _run(db)
        assert _region_of(db, cid) in (None, "")

    def test_clears_an_arabic_row_labelled_german(self, db):
        cid = _add(db, prefix="AR", region="DE")
        _run(db)
        assert _region_of(db, cid) in (None, "")

    def test_keeps_an_agreeing_region(self, db):
        cid = _add(db, prefix="IT", region="IT")
        _run(db)
        assert _region_of(db, cid) == "IT"

    def test_leaves_rows_with_no_locale_of_their_own(self, db):
        """MULTI has no locale, so an inherited region is the intended feature."""
        cid = _add(db, prefix="MULTI", region="DE")
        _run(db)
        assert _region_of(db, cid) == "DE"


class TestPlatformRows:
    """A+/D+/NF are platforms, not locales — the category is the arbiter."""

    def test_clears_when_the_category_does_not_support_it(self, db):
        cid = _add(db, prefix="A+", region="ISR", category="APPLE+ MOVIES")
        _run(db)
        assert _region_of(db, cid) in (None, ""), (
            "Apple TV+ titles under a category that names no region must not "
            "keep an inherited one"
        )

    def test_keeps_when_the_row_s_own_category_says_so(self, db):
        """Real case: D+ under 'UK| DISCOVERY +' — the UK is self-evident."""
        cid = _add(db, prefix="D+", region="UK", category="UK| DISCOVERY +")
        _run(db)
        assert _region_of(db, cid) == "UK", (
            "this region is stated by the row's own category — clearing it "
            "would destroy real information"
        )


class TestDerivedTags:

    def test_drops_the_language_tag_the_dead_region_implied(self, db):
        """The visible symptom, not just the column.

        The owner's English title carried a "German" LANGUAGE tag purely because
        it had been handed region DE — so it read as German in filters and fed
        recommendations as German. Clearing the column without the tag would
        leave that in place.
        """
        from metatv.core.database import ContentTagDB, TagDB

        cid = _add(db, prefix="EN", region="DE")
        with db.session_scope() as s:
            # TagDB.id / ContentTagDB.id are autoincrement INTEGERs — let the DB
            # assign them rather than inventing UUIDs.
            english = TagDB(type="language", value="English")
            german = TagDB(type="language", value="German")
            region = TagDB(type="region", value="DE")
            s.add_all([english, german, region])
            s.flush()
            for t in (english, german, region):
                s.add(ContentTagDB(channel_id=cid, tag_id=t.id, source="generated"))

        _run(db)

        with db.session_scope() as s:
            remaining = {
                (t.type, t.value) for t, in (
                    (row,) for row in s.query(TagDB)
                    .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
                    .filter(ContentTagDB.channel_id == cid).all()
                )
            }
        assert ("region", "DE") not in remaining, "the bogus region tag survived"
        assert ("language", "German") not in remaining, (
            "the language tag derived from the bogus region survived — the "
            "title still reads German in filters"
        )
        assert ("language", "English") in remaining, (
            "the legitimate language (from the row's own |EN| prefix) must stay"
        )


class TestIdempotency:

    def test_a_second_run_finds_nothing(self, db):
        """Only ever clears, so it converges — safe to retry after a crash."""
        cid = _add(db, prefix="EN", region="DE")
        keep = _add(db, prefix="IT", region="IT")
        _run(db)
        _run(db)
        assert _region_of(db, cid) in (None, "")
        assert _region_of(db, keep) == "IT"

    def test_needs_run_respects_the_stored_version(self, tmp_path):
        from metatv.core.config import Config
        from metatv.core.migrations.bad_region_cleanup import (
            CURRENT_VERSION, BadRegionCleanupTask,
        )

        cfg = Config(config_dir=tmp_path / "cfg")
        task = BadRegionCleanupTask(None)
        assert task.needs_run(cfg) is True
        cfg.bad_region_cleanup_version = CURRENT_VERSION
        assert task.needs_run(cfg) is False


class TestPlatformVocabularyGap:
    """v1 used the wrong platform vocabulary and missed a whole class (#276).

    ``channel_name_utils.PLATFORM_CODES`` holds 11 streaming brands;
    ``config.BASE_PLATFORM_GROUPS`` is what the tag decomposer actually
    classifies platforms from, and it includes ``SC``. So the owner's
    "4K-SC - Ballerina (2025)" — category "|SCA| NORDIC FILMS 4K", a
    Scandinavian listing — kept region ES and a "Spanish" language tag, on a
    PRECISE tmdb content_key. Precision of the key is irrelevant: content_key
    identifies the WORK, and its siblings are the same film in other locales, so
    a sibling's region says nothing about this release.
    """

    def test_clears_a_platform_group_prefix_the_small_vocabulary_missed(self, db):
        cid = _add(db, prefix="SC", region="ES", category="|SCA| NORDIC FILMS 4K")
        _run(db)
        assert _region_of(db, cid) in (None, ""), (
            "SC is in BASE_PLATFORM_GROUPS; a Scandinavian listing must not keep "
            "an inherited Spanish region"
        )

    def test_keeps_a_region_the_NAME_states(self, db):
        """"SC - Monk (US)" says US in its own name — 385 such rows.

        ParsedChannel.lang carries that parenthetical; .region carries the
        PREFIX. Reading the wrong field here would compare a platform code to a
        country and wrongly clear every one of them.
        """
        from metatv.core.database import ChannelDB

        cid = _add(db, prefix="SC", region="US", category="|SCA| MULTISUB SERIES")
        with db.session_scope() as s:
            s.query(ChannelDB).filter(ChannelDB.id == cid).update(
                {"name": "SC - Monk (US)"}
            )
        _run(db)
        assert _region_of(db, cid) == "US", (
            "the row's own name states (US) — clearing it destroys real data"
        )

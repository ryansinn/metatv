"""Tests for LANG-1: a region/catalogue code is not a film's or series' language.

Owner rule (2026-10-08): a region or regional-catalogue code (e.g. the ``SE``
prefix/category in ``"|SE| FILM 1900 - 2018"``) says only which regional
CATALOGUE a provider files a title under -- never what language it is spoken
in. For FILMS and SERIES, ``reattribute_region_languages``
(``metatv/core/tag_decomposer.py``) demotes any ``language:`` tag a region
code implies down to the low-confidence ``region_inference`` feeder (weight
0.3 in ``_compute_confidence``) so the title stays findable under "Swedish"
while any feeder that actually STATES the spoken language
(``audio_annotation``, future TMDb evidence) still outranks it. Live channels
are unaffected -- a live channel's prefix routinely IS its broadcast language.

Covers:
- the pure ``reattribute_region_languages`` unit cases from the brief,
- ``_collect_tags`` end-to-end for a row shaped like the real
  "|SE| FILM 1900 - 2018" catalogue (1,750 titles on the owner's library),
- the weighted ``_compute_confidence`` formula,
- the version-12 targeted collector (``_collect_channel_ids_region_language``)
  against a real file-backed Database.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.config import Config
from metatv.core.database import ChannelDB, Database
from metatv.core.migrations.tag_backfill import TagBackfillTask, _collect_tags
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag_content_tags import _compute_confidence
from metatv.core.tag_decomposer import reattribute_region_languages


@pytest.fixture(scope="module")
def cfg():
    """A default Config() with the base prefix/quality/platform groups."""
    return Config()


# --------------------------------------------------------------------------- #
# reattribute_region_languages -- pure unit cases                             #
# --------------------------------------------------------------------------- #


class TestReattributeRegionLanguages:
    def test_movie_se_region_demotes_swedish_language_feeders(self, cfg):
        """A movie's SE region+language (both from code feeders) demotes the
        language tag to region_inference; the region tag itself is untouched.
        """
        feeder_map = {
            ("region", "SE"): {"name_parse", "provider_category"},
            ("language", "Swedish"): {"name_parse", "provider_category"},
        }
        reattribute_region_languages(feeder_map, "movie", cfg)

        assert feeder_map[("language", "Swedish")] == {"region_inference"}
        assert feeder_map[("region", "SE")] == {"name_parse", "provider_category"}

    def test_live_channel_is_unaffected(self, cfg):
        """The identical feeder shape on a live channel is left completely alone."""
        feeder_map = {
            ("region", "SE"): {"name_parse", "provider_category"},
            ("language", "Swedish"): {"name_parse", "provider_category"},
        }
        reattribute_region_languages(feeder_map, "live", cfg)

        assert feeder_map[("language", "Swedish")] == {"name_parse", "provider_category"}
        assert feeder_map[("region", "SE")] == {"name_parse", "provider_category"}

    def test_language_not_implied_by_any_region_is_untouched(self, cfg):
        """English has no region reading implied by SE's code, so a separately
        asserted language:English tag is left completely alone."""
        feeder_map = {
            ("region", "SE"): {"name_parse"},
            ("language", "English"): {"name_parse"},
        }
        reattribute_region_languages(feeder_map, "movie", cfg)

        assert feeder_map[("language", "English")] == {"name_parse"}

    def test_real_evidence_feeder_survives_reattribution(self, cfg):
        """An audio_annotation feeder on the SAME language tag is kept -- only
        the code feeders are stripped, never a feeder that actually states the
        spoken language."""
        feeder_map = {
            ("region", "SE"): {"name_parse"},
            ("language", "Swedish"): {"name_parse", "audio_annotation"},
        }
        reattribute_region_languages(feeder_map, "movie", cfg)

        assert feeder_map[("language", "Swedish")] == {"audio_annotation", "region_inference"}


# --------------------------------------------------------------------------- #
# _collect_tags end-to-end                                                    #
# --------------------------------------------------------------------------- #


class TestCollectTagsSeFilm:
    """A row shaped like the real provider data: "SE - 3 Days To Kill" filed
    under "|SE| FILM 1900 - 2018", detected_prefix/detected_region both "SE".
    """

    _KWARGS = {
        "name": "SE - 3 Days To Kill",
        "category": "|SE| FILM 1900 - 2018",
        "source_category": None,
        "detected_prefix": "SE",
        "detected_quality": None,
        "detected_region": "SE",
        "detected_year": None,
        "raw_data": None,
    }

    def test_movie_gets_region_inference_language_only(self, cfg):
        tags = _collect_tags(config=cfg, media_type="movie", **self._KWARGS)

        assert ("region", "SE", "name_parse") in tags
        assert ("region", "SE", "provider_category") in tags
        assert ("language", "Swedish", "region_inference") in tags
        assert ("language", "Swedish", "name_parse") not in tags
        assert ("language", "Swedish", "provider_category") not in tags

    def test_live_channel_keeps_the_old_feeders(self, cfg):
        tags = _collect_tags(config=cfg, media_type="live", **self._KWARGS)

        assert ("language", "Swedish", "name_parse") in tags
        assert ("language", "Swedish", "provider_category") in tags
        assert ("language", "Swedish", "region_inference") not in tags


# --------------------------------------------------------------------------- #
# _compute_confidence -- weighted formula                                     #
# --------------------------------------------------------------------------- #


class TestComputeConfidenceWeighted:
    def test_region_inference_alone_reads_low(self):
        assert _compute_confidence(["region_inference"]) == pytest.approx(0.1)

    def test_region_inference_plus_real_evidence(self):
        assert _compute_confidence(
            ["region_inference", "audio_annotation"]
        ) == pytest.approx(1.3 / 3)

    def test_unweighted_feeder_unchanged(self):
        """Confirms the LANG-1 weighting change didn't alter the original
        pure-count behaviour for any feeder outside _FEEDER_WEIGHTS."""
        assert _compute_confidence(["name_parse"]) == pytest.approx(1 / 3)


# --------------------------------------------------------------------------- #
# Version-12 targeted collector                                               #
# --------------------------------------------------------------------------- #


def _add_channel(db: Database, *, media_type: str | None = None) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    channel_id = str(uuid.uuid4())
    with db.session_scope() as session:
        ch = ChannelDB(
            id=channel_id,
            source_id=str(uuid.uuid4()),
            provider_id="test_provider",
            name="Test Channel",
            media_type=media_type,
        )
        session.add(ch)
    return channel_id


class TestRegionLanguageTargetedCollector:
    def test_collector_finds_only_movie_series_with_region_tag(self, file_db, cfg):
        """_collect_channel_ids_region_language returns exactly the
        movie/series channels carrying a region: content_tag -- not a live
        channel's region tag, and not a movie with no region tag at all."""
        movie_with_region = _add_channel(file_db, media_type="movie")
        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                movie_with_region,
                [("region", "SE", "provider_category")],
                source="generated",
            )

        live_with_region = _add_channel(file_db, media_type="live")
        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                live_with_region,
                [("region", "SE", "provider_category")],
                source="generated",
            )

        movie_without_region = _add_channel(file_db, media_type="movie")
        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                movie_without_region,
                [("genre", "Action", "provider_category")],
                source="generated",
            )

        task = TagBackfillTask(file_db, config=cfg)
        found = set(task._collect_channel_ids_region_language())

        assert found == {movie_with_region}
        assert live_with_region not in found
        assert movie_without_region not in found

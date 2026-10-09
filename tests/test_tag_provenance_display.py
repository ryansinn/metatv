"""Behavioral tests for tag provenance + confidence display (DR-0006, task #13).

Pins two invariants:
1. ``TagRepository.get_channel_tags_dto`` returns correct ``source_given`` /
   ``confidence`` / ``feeders`` for seeded content_tags rows — including that
   a ``provider_category`` feeder yields ``source_given=True`` and a
   ``name_parse`` feeder yields ``source_given=False``.
2. ``_TagsSection.load`` (main-thread render slot), given a list of
   ChannelTagDTOs, groups tags by facet, renders chip labels with the correct
   provenance icon, and applies the right stylesheet tokens (TAG_CHIP_SOURCE vs
   TAG_CHIP_INFERRED) — verified headlessly without a running window.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from metatv.core.database import ChannelDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import ChannelTagDTO, _SOURCE_GIVEN_FEEDERS
from metatv.gui import icons as _icons
from tests.conftest import make_file_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Process-wide QApplication for headless Qt widget tests."""
    from PyQt6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


def _make_channel(session, name: str = "Test Channel") -> ChannelDB:
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id="src1",
        provider_id="prov1",
        name=name,
    )
    session.add(ch)
    session.flush()
    return ch


def _fake_config(**overrides):
    """Minimal config namespace for _TagsSection."""
    defaults = {
        "collapse_icon": _icons.collapse_icon,
        "expand_icon": _icons.expand_icon,
        "details_pane_collapsed_sections": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# 1. Repository: get_channel_tags_dto returns correct DTOs
# ---------------------------------------------------------------------------

class TestGetChannelTagsDto:
    """Tag repo returns ChannelTagDTOs with correct source_given / confidence."""

    def test_source_given_true_for_provider_category_feeder(self, tmp_path):
        """A tag whose only feeder is 'provider_category' must be source_given=True."""
        db = make_file_db(tmp_path / "tags_test.db")
        with db.session_scope() as session:
            ch = _make_channel(session, "EN | Action Movie")
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                ch.id,
                [("genre", "Action", "provider_category")],
                source="generated",
            )
            dtos = repos.tags.get_channel_tags_dto(ch.id)

        assert len(dtos) == 1
        dto = dtos[0]
        assert dto.facet_type == "genre"
        assert dto.value == "Action"
        assert dto.source_given is True, (
            "provider_category feeder must yield source_given=True (DR-0006)"
        )
        assert dto.confidence > 0.0
        assert "provider_category" in dto.feeders

    def test_source_given_false_for_name_parse_feeder(self, tmp_path):
        """A tag whose only feeder is 'name_parse' must be source_given=False."""
        db = make_file_db(tmp_path / "tags_test.db")
        with db.session_scope() as session:
            ch = _make_channel(session, "EN - Drama Show")
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                ch.id,
                [("language", "English", "name_parse")],
                source="generated",
            )
            dtos = repos.tags.get_channel_tags_dto(ch.id)

        assert len(dtos) == 1
        dto = dtos[0]
        assert dto.source_given is False, (
            "name_parse feeder must yield source_given=False (DR-0006 inferred)"
        )
        assert "name_parse" in dto.feeders

    def test_source_given_true_when_any_feeder_is_provider(self, tmp_path):
        """Mixed feeders: source_given=True when ANY feeder is a provider-field reader."""
        db = make_file_db(tmp_path / "tags_test.db")
        with db.session_scope() as session:
            ch = _make_channel(session, "US | Drama")
            repos = RepositoryFactory(session)
            # Insert with inferred feeder, then update with provider feeder via upsert
            repos.tags.set_content_tags(
                ch.id,
                [("region", "US", "name_parse")],
                source="generated",
            )
            repos.tags.set_content_tags(
                ch.id,
                [("region", "US", "provider_category")],
                source="generated",
            )
            dtos = repos.tags.get_channel_tags_dto(ch.id)

        region_dto = next(d for d in dtos if d.facet_type == "region")
        assert region_dto.source_given is True, (
            "Tag with both provider_category and name_parse feeders must be source_given=True"
        )
        assert len(region_dto.feeders) == 2

    def test_confidence_increases_with_feeder_count(self, tmp_path):
        """Confidence grows as more distinct feeders assert the same tag."""
        db = make_file_db(tmp_path / "tags_test.db")
        with db.session_scope() as session:
            ch = _make_channel(session, "FR | Cinema")
            repos = RepositoryFactory(session)
            # One feeder → confidence ≈ 0.33
            repos.tags.set_content_tags(
                ch.id,
                [("language", "French", "provider_category")],
                source="generated",
            )
            dtos_one = repos.tags.get_channel_tags_dto(ch.id)
            conf_one = dtos_one[0].confidence

            # Two feeders → confidence ≈ 0.67
            repos.tags.set_content_tags(
                ch.id,
                [("language", "French", "name_parse")],
                source="generated",
            )
            dtos_two = repos.tags.get_channel_tags_dto(ch.id)
            conf_two = dtos_two[0].confidence

        assert conf_two > conf_one, (
            "Confidence must increase as more distinct feeders assert the same tag"
        )

    def test_empty_result_for_channel_with_no_tags(self, tmp_path):
        """Channel with zero tags returns an empty list, not an error."""
        db = make_file_db(tmp_path / "tags_test.db")
        with db.session_scope() as session:
            ch = _make_channel(session, "Untagged Channel")
            repos = RepositoryFactory(session)
            dtos = repos.tags.get_channel_tags_dto(ch.id)

        assert dtos == []

    def test_genre_feeder_is_source_given(self, tmp_path):
        """The 'genre' feeder (provider raw_data field) must be source_given=True."""
        db = make_file_db(tmp_path / "tags_test.db")
        with db.session_scope() as session:
            ch = _make_channel(session, "Movie (2020)")
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                ch.id,
                [("genre", "Drama", "genre")],
                source="generated",
            )
            dtos = repos.tags.get_channel_tags_dto(ch.id)

        assert dtos[0].source_given is True, (
            "'genre' feeder is a direct provider field — must be source_given=True"
        )

    def test_epg_feeder_is_inferred(self, tmp_path):
        """The 'epg' feeder (derived from EPG category) must be source_given=False."""
        db = make_file_db(tmp_path / "tags_test.db")
        with db.session_scope() as session:
            ch = _make_channel(session, "Sports Channel")
            repos = RepositoryFactory(session)
            repos.tags.set_content_tags(
                ch.id,
                [("genre", "Sport", "epg")],
                source="generated",
            )
            dtos = repos.tags.get_channel_tags_dto(ch.id)

        assert dtos[0].source_given is False, (
            "'epg' feeder is a secondary inference — must be source_given=False"
        )

    def test_dto_is_frozen_dataclass(self, tmp_path):
        """ChannelTagDTO must be immutable (frozen=True) so it's safe across threads."""
        dto = ChannelTagDTO(
            facet_type="genre",
            value="Drama",
            source_given=True,
            confidence=0.9,
            feeders=("provider_category",),
        )
        with pytest.raises((AttributeError, TypeError)):
            dto.value = "Comedy"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. _TagsSection render: correct grouping, provenance icons, stylesheets
# ---------------------------------------------------------------------------

class TestDetailsSectionRender:
    """_DetailsSection groups facts by where they came from (DETAILS-3d)."""

    def _make_section(self, owned_widgets, config=None):
        from metatv.gui.details_facts import _DetailsSection
        sec = owned_widgets.own(_DetailsSection(config or _fake_config()))
        sec.set_copy(provider_name="TREX", copy_code="EN")
        return sec

    def test_section_hidden_with_empty_tags(self, qapp, owned_widgets):
        sec = self._make_section(owned_widgets)
        sec.load_tags([])
        assert not sec.isVisible(), "Details must hide when there is nothing to say"

    def test_section_visible_with_tags(self, qapp, owned_widgets):
        sec = self._make_section(owned_widgets)
        sec.load_tags([ChannelTagDTO("language", "English", True, 0.9, ("provider_category",))])
        assert sec.isVisible()

    def test_header_names_the_copy(self, qapp, owned_widgets):
        sec = self._make_section(owned_widgets)
        assert sec._header._title.text().startswith("Details for "), (
            "the heading must say WHICH copy these facts describe"
        )
        assert "(EN)" in sec._header._title.text()

    def test_summary_states_the_fact_count(self, qapp, owned_widgets):
        sec = self._make_section(owned_widgets)
        sec.load_tags([
            ChannelTagDTO("language", "French", False, 0.33, ("name_parse",)),
            ChannelTagDTO("region", "US", True, 0.9, ("provider_category",)),
        ])
        assert sec._header.summary() == "2"
        sec.load_tags([])
        assert sec._header.summary() == ""

    def test_genre_and_collection_stay_in_the_title_block(self, qapp, owned_widgets):
        sec = self._make_section(owned_widgets)
        sec.load_tags([
            ChannelTagDTO("genre", "Drama", True, 0.9, ("provider_category",)),
            ChannelTagDTO("collection", "Peliculas 2024", True, 0.9, ("provider_category",)),
            ChannelTagDTO("language", "Spanish", True, 0.9, ("provider_category",)),
        ])
        facets = {c.property("facet") for c in _collect_chips(sec)}
        assert facets == {"language"}, f"genre/collection must not repeat here: {facets}"

    def _captions(self, sec) -> list[str]:
        from PyQt6.QtWidgets import QLabel
        return [w.text() for w in sec.findChildren(QLabel) if w.text().startswith("· ")]

    def test_each_fact_names_its_source(self, qapp, owned_widgets):
        sec = self._make_section(owned_widgets)
        sec.load_tags([ChannelTagDTO("region", "SE", True, 0.9, ("provider_category",))])
        assert self._captions(sec) == ["· TREX"], "a stated fact names the source it came from"

    def test_a_guess_is_italic_and_says_why(self, qapp, owned_widgets):
        sec = self._make_section(owned_widgets)
        sec.load_tags([
            ChannelTagDTO("language", "Swedish", False, 0.1, ("region_inference",)),
            ChannelTagDTO("region", "SE", True, 0.9, ("provider_category",)),
        ])
        guess = [c for c in _collect_chips(sec) if c.property("value") == "Swedish"][0]
        assert "italic" in guess.styleSheet(), "a guessed fact must read as a guess"
        fact = [c for c in _collect_chips(sec) if c.property("value") == "SE"][0]
        assert "italic" not in fact.styleSheet()
        why = [c for c in self._captions(sec) if c.startswith("· guessed from region")]
        assert why and "(SE)" in why[0], f"the guess must say why: {self._captions(sec)}"

    def test_release_date_is_a_fact(self, qapp, owned_widgets):
        from types import SimpleNamespace
        from PyQt6.QtWidgets import QLabel
        sec = self._make_section(owned_widgets)
        sec.load_metadata(SimpleNamespace(release_date="2024-12-20", provider_name="TMDb"))
        assert sec.isVisible()
        assert any(w.text() == "2024-12-20" for w in sec.findChildren(QLabel))
        assert self._captions(sec) == ["· TMDb"]

    def test_clear_hides_section(self, qapp, owned_widgets):
        sec = self._make_section(owned_widgets)
        sec.load_tags([ChannelTagDTO("language", "English", True, 1.0, ("provider_category",))])
        assert sec.isVisible()
        sec.clear()
        assert not sec.isVisible()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_chips(section) -> list:
    """Every fact chip in the section (the header's own button excluded)."""
    from PyQt6.QtWidgets import QPushButton
    return [c for c in section.findChildren(QPushButton) if c.property("facet")]


# ---------------------------------------------------------------------------
# 3. _SOURCE_GIVEN_FEEDERS coverage sanity
# ---------------------------------------------------------------------------

class TestSourceGivenFeedersSet:
    """The _SOURCE_GIVEN_FEEDERS constant must include the canonical provider feeders."""

    def test_provider_category_in_source_given(self, owned_widgets):
        assert "provider_category" in _SOURCE_GIVEN_FEEDERS

    def test_genre_in_source_given(self, owned_widgets):
        assert "genre" in _SOURCE_GIVEN_FEEDERS

    def test_user_in_source_given(self, owned_widgets):
        assert "user" in _SOURCE_GIVEN_FEEDERS

    def test_name_parse_not_in_source_given(self, owned_widgets):
        assert "name_parse" not in _SOURCE_GIVEN_FEEDERS

    def test_header_not_in_source_given(self, owned_widgets):
        assert "header" not in _SOURCE_GIVEN_FEEDERS

    def test_epg_not_in_source_given(self, owned_widgets):
        assert "epg" not in _SOURCE_GIVEN_FEEDERS

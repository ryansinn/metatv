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

import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.core.database import Database, ChannelDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import ChannelTagDTO, _SOURCE_GIVEN_FEEDERS
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


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


def _make_db(tmp_path: Path) -> Database:
    db_path = tmp_path / "tags_test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    return db


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
    defaults = dict(
        collapse_icon=_icons.collapse_icon,
        expand_icon=_icons.expand_icon,
        details_pane_collapsed_sections=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# 1. Repository: get_channel_tags_dto returns correct DTOs
# ---------------------------------------------------------------------------

class TestGetChannelTagsDto:
    """Tag repo returns ChannelTagDTOs with correct source_given / confidence."""

    def test_source_given_true_for_provider_category_feeder(self, tmp_path):
        """A tag whose only feeder is 'provider_category' must be source_given=True."""
        db = _make_db(tmp_path)
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
        db = _make_db(tmp_path)
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
        db = _make_db(tmp_path)
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
        db = _make_db(tmp_path)
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
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            ch = _make_channel(session, "Untagged Channel")
            repos = RepositoryFactory(session)
            dtos = repos.tags.get_channel_tags_dto(ch.id)

        assert dtos == []

    def test_genre_feeder_is_source_given(self, tmp_path):
        """The 'genre' feeder (provider raw_data field) must be source_given=True."""
        db = _make_db(tmp_path)
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
        db = _make_db(tmp_path)
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

class TestTagsSectionRender:
    """_TagsSection.load groups chips by facet and applies correct styles."""

    def _make_section(self, config=None):
        from metatv.gui.details_sections import _TagsSection
        config = config or _fake_config()
        # Construct without __init__ to avoid requiring a QApplication for non-Qt tests;
        # but _TagsSection inherits QWidget so we need qapp — handled at the method level.
        return _TagsSection(config)

    def test_section_hidden_with_empty_tags(self, qapp):
        """Section must be hidden (not shown) when given an empty tags list."""
        sec = self._make_section()
        sec.load([])
        assert not sec.isVisible(), "Tags section must hide when tag list is empty"

    def test_section_visible_with_tags(self, qapp):
        """Section must become visible when tags are present."""
        sec = self._make_section()
        tags = [
            ChannelTagDTO("language", "English", True, 0.9, ("provider_category",)),
        ]
        sec.load(tags)
        assert sec.isVisible(), "Tags section must show when there are tags to display"

    def test_source_given_chip_uses_source_stylesheet(self, qapp):
        """A source-given tag chip must use TAG_CHIP_SOURCE stylesheet."""
        sec = self._make_section()
        tags = [
            ChannelTagDTO("genre", "Drama", True, 0.9, ("provider_category",)),
        ]
        sec.load(tags)

        # Find the QPushButton chip(s) in the content layout
        chips = _collect_chips(sec)
        assert len(chips) == 1
        assert chips[0].styleSheet() == _theme.TAG_CHIP_SOURCE, (
            "Source-given chip must use TAG_CHIP_SOURCE stylesheet"
        )

    def test_inferred_chip_uses_inferred_stylesheet(self, qapp):
        """An inferred tag chip must use TAG_CHIP_INFERRED stylesheet."""
        sec = self._make_section()
        tags = [
            ChannelTagDTO("language", "French", False, 0.33, ("name_parse",)),
        ]
        sec.load(tags)

        chips = _collect_chips(sec)
        assert len(chips) == 1
        assert chips[0].styleSheet() == _theme.TAG_CHIP_INFERRED, (
            "Inferred chip must use TAG_CHIP_INFERRED stylesheet"
        )

    def test_chip_label_includes_provenance_icon(self, qapp):
        """Chip text must include the provenance icon (■ or □)."""
        sec = self._make_section()
        tags = [
            ChannelTagDTO("region", "US", True, 0.9, ("provider_category",)),
            ChannelTagDTO("language", "French", False, 0.33, ("name_parse",)),
        ]
        sec.load(tags)

        chips = _collect_chips(sec)
        texts = [c.text() for c in chips]
        # At least one chip must contain the source-given icon
        assert any(_icons.tag_source_given_icon in t for t in texts), (
            "At least one chip must contain the source-given icon (■)"
        )
        # At least one chip must contain the inferred icon
        assert any(_icons.tag_inferred_icon in t for t in texts), (
            "At least one chip must contain the inferred icon (□)"
        )

    def test_chip_has_tooltip_with_feeder_and_confidence(self, qapp):
        """Each chip must have a tooltip containing feeders + confidence info."""
        sec = self._make_section()
        tags = [
            ChannelTagDTO("genre", "Action", False, 0.33, ("name_parse",)),
        ]
        sec.load(tags)

        chips = _collect_chips(sec)
        assert len(chips) == 1
        tip = chips[0].toolTip()
        assert "name_parse" in tip, "Tooltip must mention the feeder name"
        assert "33%" in tip or "33" in tip, "Tooltip must mention the confidence percentage"
        assert "Inferred by MetaTV" in tip, "Tooltip must state provenance label"

    def test_clear_hides_section(self, qapp):
        """After load, clear() must hide the section."""
        sec = self._make_section()
        tags = [ChannelTagDTO("genre", "Drama", True, 1.0, ("provider_category",))]
        sec.load(tags)
        assert sec.isVisible()
        sec.clear()
        assert not sec.isVisible(), "Tags section must hide after clear()"

    def test_grouped_by_facet_renders_multiple_rows(self, qapp):
        """Tags from different facets render as separate groups."""
        sec = self._make_section()
        tags = [
            ChannelTagDTO("language", "English", True, 0.9, ("provider_category",)),
            ChannelTagDTO("genre", "Drama", False, 0.33, ("name_parse",)),
            ChannelTagDTO("region", "US", True, 0.67, ("provider_category", "name_parse")),
        ]
        sec.load(tags)

        # All 3 chips must be rendered
        chips = _collect_chips(sec)
        assert len(chips) == 3, (
            f"Expected 3 chips (one per tag), got {len(chips)}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_chips(section) -> list:
    """Walk the content widget tree and collect all QPushButton chips."""
    from PyQt6.QtWidgets import QPushButton, QWidget

    result = []
    content = section._content
    layout = content.layout()
    if layout is None:
        return result
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        widget = item.widget()
        if widget is None:
            continue
        # Each facet group is a QWidget row containing QPushButtons
        row_layout = widget.layout()
        if row_layout is None:
            continue
        for j in range(row_layout.count()):
            sub = row_layout.itemAt(j)
            if sub and sub.widget() and isinstance(sub.widget(), QPushButton):
                result.append(sub.widget())
    return result


# ---------------------------------------------------------------------------
# 3. _SOURCE_GIVEN_FEEDERS coverage sanity
# ---------------------------------------------------------------------------

class TestSourceGivenFeedersSet:
    """The _SOURCE_GIVEN_FEEDERS constant must include the canonical provider feeders."""

    def test_provider_category_in_source_given(self):
        assert "provider_category" in _SOURCE_GIVEN_FEEDERS

    def test_genre_in_source_given(self):
        assert "genre" in _SOURCE_GIVEN_FEEDERS

    def test_user_in_source_given(self):
        assert "user" in _SOURCE_GIVEN_FEEDERS

    def test_name_parse_not_in_source_given(self):
        assert "name_parse" not in _SOURCE_GIVEN_FEEDERS

    def test_header_not_in_source_given(self):
        assert "header" not in _SOURCE_GIVEN_FEEDERS

    def test_epg_not_in_source_given(self):
        assert "epg" not in _SOURCE_GIVEN_FEEDERS

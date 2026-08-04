"""The details pane showed the provider's raw genre wording (#294).

Owner: "we spent a lot of time normalizing all these variations of
categories/tags/genres into English and it looks like these have been reverted."

Nothing was reverted. ``normalize_genre`` (filter_utils.py:1139) maps
drame/dramma/commedia/documentaire → the canonical English key, is applied at
ingestion (tag_decomposer) and in stat aggregation (channel_stats) — and had
ZERO callers in ``metatv/gui``, despite its own docstring saying it exists "so a
genre clicked in the details pane maps to the same filter-panel key". The pane
was the one read path that never used it.

Measured on the owner's library, channel ...e1_6984 ("FR - Kiss Me First"):

    channels.detected_genres = ["Drama", "Mystery", "Sci-Fi & Fantasy"]   ← list row
    metadata.genres          = Drame / Mystère / Science-Fiction & …      ← details pane

Both rendered on screen at the same time: the row said "Drama", the pane said
"Drame". One fact, two answers.

This canonicalizes PRESENTATION only — ``metadata.genres`` keeps the provider's
own wording, so no language variant is destroyed, and when the UI speaks other
languages the display layer slots in over the same key.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

from metatv.core.config import Config
from metatv.metadata_providers.base import MetadataResult


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _metadata(genres):
    """The REAL MetadataResult the pane is given in production."""
    return MetadataResult(title="Kiss Me First", genres=list(genres))


@pytest.fixture()
def section(qapp):
    from metatv.gui.details_sections import _MetadataSection

    sec = _MetadataSection(Config())
    sec.show()
    QApplication.processEvents()
    yield sec
    sec.hide()


def _chip_texts(section) -> list[str]:
    layout = section._genres_layout
    out = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if isinstance(w, QPushButton):
            out.append(w.text().replace("&&", "&"))
    return out


@pytest.mark.parametrize(
    "raw, expected",
    [
        # The owner's two screenshots, verbatim from the provider payloads.
        (["Drame", "Mystère", "Science-Fiction & Fantastique"], "Drama"),
        (["Crime / Dramma"], "Drama"),
        # Other localised spellings the table already knew about.
        (["Commedia"], "Comedy"),
        (["Documentaire"], "Documentary"),
        (["Komedie"], "Comedy"),
        (["Krimi"], "Crime"),
    ],
)
def test_localised_provider_genres_render_canonically(section, raw, expected):
    """The pane must not show the provider's own wording."""
    section.load_metadata(_metadata(raw))
    QApplication.processEvents()

    texts = _chip_texts(section)
    assert expected in texts, f"{raw} rendered as {texts}, expected {expected!r}"
    for original in raw:
        leaf = original.split("/")[-1].strip()
        if leaf.casefold() != expected.casefold():
            assert leaf not in texts, (
                f"raw provider wording {leaf!r} is still on screen"
            )


def test_it_agrees_with_what_the_list_row_shows(section):
    """The actual defect: two surfaces disagreeing about one channel.

    The delegate reads the ingestion-computed ``detected_genre``; this pane
    reads ``metadata.genres``. Given the same title they must now agree.
    """
    list_row_value = "Drama"                       # channels.detected_genre
    section.load_metadata(_metadata(["Drame"]))   # metadata.genres
    QApplication.processEvents()

    assert list_row_value in _chip_texts(section)


def test_already_canonical_genres_are_untouched(section):
    """No over-correction: an English payload passes straight through."""
    section.load_metadata(
        _metadata(["Action & Adventure", "Sci-Fi & Fantasy"])
    )
    QApplication.processEvents()

    assert _chip_texts(section) == ["Action & Adventure", "Sci-Fi & Fantasy"]


def test_variants_that_fold_together_produce_one_chip(section):
    """"Drame" and "Drama" from two merged providers are the same genre."""
    section.load_metadata(_metadata(["Drame", "Drama", "Dramma"]))
    QApplication.processEvents()

    assert _chip_texts(section).count("Drama") == 1


def test_the_click_emits_the_canonical_key(section):
    """A chip click drives a filter, and the filter keys are canonical.

    Emitting "Drame" would search a facet value that aggregation never
    produces — the click would silently match nothing.
    """
    seen: list[str] = []
    section.genre_clicked.connect(seen.append)

    section.load_metadata(_metadata(["Drame"]))
    QApplication.processEvents()
    next(
        w for i in range(section._genres_layout.count())
        if isinstance(w := section._genres_layout.itemAt(i).widget(), QPushButton)
    ).click()

    assert seen == ["Drama"], f"clicked chip emitted {seen}"


def test_an_unknown_genre_is_passed_through_not_dropped(section):
    """The table is a known-alias map, not a whitelist.

    A genre nobody has mapped yet must still show — dropping it would be
    censorial about the one thing the provider actually told us.
    """
    section.load_metadata(_metadata(["Tokusatsu"]))
    QApplication.processEvents()

    assert "Tokusatsu" in _chip_texts(section)

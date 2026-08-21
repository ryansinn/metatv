"""The clickable-metadata pieces of the lightbox card: chips, links, lens strip.

One small module for the three widgets/renderers that make a title's metadata
navigable inside the preview overlay — a genre chip you can click, cast/crew
names rendered as links, and the strip that names the resulting *lens* and
carries the single explicit hand-off out to the channel list.

They live together because they are one concern (turn metadata into
navigation), and apart from ``similar_lightbox_card.py`` because that card is
at the 1000-line ceiling the code-health ratchet enforces.

Colour note: the lightbox card is a deliberately fixed-dark "cinema" surface in
every palette, so link text uses ``COLOR_LIGHTBOX_LINK`` — that family's own
fixed accent. A palette-tuned accent cannot be used here: Daylight's is a dark
navy chosen for a LIGHT app surface and reads at 1.2:1 on this card.
"""
from __future__ import annotations

import html

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable


class ClickableChip(QLabel):
    """A chip label that emits :attr:`clicked` — the genre-lens trigger.

    A real subclass, not an instance-level ``mousePressEvent`` assignment:
    that does NOT override Qt's virtual dispatch (the trap the lightbox's
    poster slot documents).
    """

    clicked = pyqtSignal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        set_clickable(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit()
        super().mousePressEvent(event)


def genre_chips(genres, on_click) -> list[ClickableChip]:
    """Build a title's clickable genre chips.

    Args:
        genres: Genre names as displayed; blanks are skipped.
        on_click: Called with the genre name when a chip is clicked.

    Returns:
        The chips, in order — the caller adds them to its own flow layout.
    """
    chips: list[ClickableChip] = []
    for genre in genres or []:
        genre = (genre or "").strip()
        if not genre:
            continue
        chip = ClickableChip(genre)
        _theme.style(chip, "LIGHTBOX_GENRE_CHIP")
        chip.setToolTip(f"Show {genre} titles")
        chip.clicked.connect(lambda name=genre: on_click(name))
        chips.append(chip)
    return chips


def person_link(name: str) -> str:
    """One cast/crew name as a lens link.

    ``href`` is the raw name — ``linkActivated`` hands it straight back as the
    lens value, so nothing has to parse a display string to recover it.
    """
    href = html.escape(name, quote=True)
    return (
        f'<a href="{href}" style="color:{_theme.COLOR_LIGHTBOX_LINK};'
        f' text-decoration:none;">{html.escape(name)}</a>'
    )


def cast_links_html(people) -> tuple[str, bool]:
    """Render structured cast + crew as the card's one-line credits, linked.

    Args:
        people: ``[{"name": …, "role": "cast"|"director"}]``, or a plain
            display STRING. A string renders unlinked: a caller holding only a
            display line cannot say where one name ends and the next begins,
            and splitting on commas would invent links to fragments.

    Returns:
        ``(html, linked)`` — the markup for the credits label, and whether any
        of it is actually clickable (drives the label's tooltip).
    """
    if isinstance(people, str):
        return people, False

    rows = [p for p in (people or []) if isinstance(p, dict)]
    names = [
        (p.get("name") or "").strip() for p in rows if p.get("role") != "director"
    ]
    directors = [
        (p.get("name") or "").strip() for p in rows if p.get("role") == "director"
    ]
    names = [n for n in names if n]
    directors = [n for n in directors if n]

    actors = ", ".join(person_link(n) for n in names)
    if directors:
        crew = ", ".join(person_link(n) for n in directors)
        text = f"{actors} · dir. {crew}" if actors else f"dir. {crew}"
    else:
        text = actors
    return text, bool(names or directors)


class LensBar(QWidget):
    """Strip naming the facet set the overlay is currently paging.

    Visible only inside a lens. It carries the ONE hand-off to the channel
    list: that list sits hidden behind the overlay, so committing to it has to
    be an explicit choice the user makes, never something a metadata click does
    quietly on their behalf.
    """

    search_requested = pyqtSignal(str, str)  # lens ("person"/"genre"), value

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _theme.style(self, "LIGHTBOX_LENS_BAR")
        self._lens: tuple[str, str] | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 6, 12, 6)
        row.setSpacing(8)

        self._label = QLabel()
        _theme.style(self._label, "LIGHTBOX_LENS_LABEL")
        row.addWidget(self._label, 1)

        self._search_btn = QPushButton("See all in Search →")
        self._search_btn.setFlat(True)
        _theme.style(self._search_btn, "LIGHTBOX_LENS_LINK")
        self._search_btn.setToolTip(
            "Close the preview and filter the channel list by this"
        )
        set_clickable(self._search_btn)
        self._search_btn.clicked.connect(self._emit_search)
        row.addWidget(self._search_btn)

        self.hide()

    def set_lens(self, label: str, lens: str, value: str) -> None:
        """Name the set being paged and show the strip."""
        self._lens = (lens, value)
        self._label.setText(label)
        self.show()

    def clear(self) -> None:
        """Leave the lens — back on a title's own neighbours."""
        self._lens = None
        self.hide()

    @property
    def lens(self) -> tuple[str, str] | None:
        return self._lens

    @property
    def label_text(self) -> str:
        return self._label.text()

    def _emit_search(self) -> None:
        if self._lens:
            self.search_requested.emit(*self._lens)

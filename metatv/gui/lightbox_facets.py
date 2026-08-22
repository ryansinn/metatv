"""The clickable-metadata pieces of the lightbox card: chips, links, lens strip.

One small module for the pieces that make a title's metadata navigable inside
the preview overlay — a genre chip you can click, cast/crew names rendered as
links, and the one-line notice shown when a click matched nothing.

The lens's exit to the channel list is NOT here: it lives in the card header,
beside the name it applies to. An earlier cut gave the lens its own full-width
strip that repeated the header's label and read as a disabled text input.

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

from PyQt6.QtCore import QObject, pyqtSignal
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


class LensNotice(QWidget):
    """A one-line notice under the header, for a click that produced nothing.

    Every other facet click is self-evidencing: the overlay re-seeds, the header
    renames itself, the breadcrumb grows a crumb. The empty case has none of
    that — nothing to navigate to — so it is the one that needs to be said out
    loud, on the card the user is already looking at.

    It clears itself on the next navigation, so it never becomes furniture.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _theme.style(self, "LIGHTBOX_NOTICE_BAR")

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 5, 12, 5)
        row.setSpacing(8)

        self._label = QLabel()
        _theme.style(self._label, "LIGHTBOX_NOTICE_TEXT")
        row.addWidget(self._label, 1)

        self.hide()

    def show_notice(self, text: str) -> None:
        """Say what happened, and show the line."""
        self._label.setText(text)
        self.show()

    def clear(self) -> None:
        """Hide the line (any navigation supersedes it)."""
        self._label.clear()
        self.hide()

    @property
    def text(self) -> str:
        return self._label.text()


class LensChrome(QObject):
    """The card's facet-lens chrome: the exit link, and the empty-click notice.

    Two widgets that live in different places on the card — the exit button goes
    in the header row, beside the name of the lens it applies to; the notice
    goes under it — but they are one concern and one state machine, so the card
    holds this instead of four widgets and four flags.

    Deliberately NOT a strip of its own. An earlier cut gave the lens a
    full-width bar under the header carrying its name plus the exit; the name
    repeated the header verbatim, and the stretched label read as a disabled
    text input. The header names the lens, the breadcrumb names its anchor, and
    what is left over is what lives here.
    """

    search_requested = pyqtSignal(str, str)  # lens ("person"/"genre"), value

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lens: tuple[str, str] | None = None

        self.exit_button = QPushButton("See all in Search →")
        self.exit_button.setFlat(True)
        _theme.style(self.exit_button, "LIGHTBOX_LENS_LINK")
        self.exit_button.setToolTip(
            "Close the preview and filter the channel list by this"
        )
        set_clickable(self.exit_button)
        self.exit_button.clicked.connect(self._emit_search)
        self.exit_button.hide()

        self.notice = LensNotice()

    def set_lens(self, lens: str, value: str) -> None:
        """Enter a lens: offer the exit, drop any stale notice."""
        self._lens = (lens, value)
        self.exit_button.show()
        self.notice.clear()

    def clear(self) -> None:
        """Leave the lens (back on a title's own neighbours)."""
        self._lens = None
        self.exit_button.hide()
        self.notice.clear()

    def show_notice(self, text: str) -> None:
        """Say that a click matched nothing — the one case with no navigation."""
        self.notice.show_notice(text)

    @property
    def lens(self) -> tuple[str, str] | None:
        return self._lens

    def _emit_search(self) -> None:
        if self._lens:
            self.search_requested.emit(*self._lens)

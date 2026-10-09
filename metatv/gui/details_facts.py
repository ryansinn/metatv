"""The details pane's "Details for <copy>" section (DETAILS-3d).

Every stored fact about the copy on screen, grouped by WHERE it came from —
"From <source>", "From TMDb", "Yours", "In the title", "Guessed" — rather than
by a confidence score. Genre and collection are not here: both already sit in
the title block above. A guessed fact is dashed and carries its reason
("from the name", "from region Sweden (SE)") beside it.

Facts describe ONE copy. Nothing is merged in from the other copies of the
title: a copy's language, subtitles and audio are its own, and a merged list
would claim the English copy has Swedish audio.

Replaces the old Tags and Technical Details sections; the release date that
Technical carried is a row here.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from metatv.core.channel_name_utils import content_type_display
from metatv.core.tag_provenance import GROUP_ORDER, group_label, guess_reason, strongest_kind
from metatv.gui import theme as _theme
from metatv.gui.detail_chips import (
    KEY_COL, SECTION_INDENT, display_code, make_chip, make_flow, make_key, make_label_grid,
)
from metatv.gui.details_section_header import CollapsibleHeader, CollapsibleMixin

# Canonical facet order inside a group. "category" sits immediately before
# "genre" — both are content descriptors; category is the live-channel variant.
_FACET_DISPLAY_ORDER: list[str] = [
    "language", "subtitle", "dub", "format",
    "region", "category", "genre", "platform", "quality", "decade", "collection",
]

# Key-column label for each facet type.
_FACET_LABELS: dict[str, str] = {
    "language":    "Language",
    "subtitle":    "Subtitles",
    "dub":         "Dubbed",
    "format":      "Audio",
    "region":      "Region",
    "category":    "Category",
    "genre":       "Genre",
    "platform":    "Platform",
    "quality":     "Quality",
    "decade":      "Decade",
    "collection":  "Collection",
    "content_type": "Content",
    # Named in the provider's filename, NOT verified credits — the label says so
    # because this facet sits a few inches from the authoritative Cast section
    # and the two must never read as the same claim. A provider typo
    # ("Denzel Washigton") lands here honestly; it must not look like a credit.
    "person":      "Named in Title",
}

# Shown in the title block above, never repeated here.
_TITLE_BLOCK_FACETS = frozenset({"genre", "collection"})


def _facet_colour_token(facet: str) -> str:
    """The facet's own hue token when the palette has one, else body text."""
    token = f"COLOR_FACET_{facet.upper()}"
    return token if hasattr(_theme, token) else "COLOR_TEXT"


class _DetailsSection(CollapsibleMixin, QWidget):
    """Collapsible "Details for <copy>" — stored facts grouped by provenance.

    Left-click a value → ``tag_filter_clicked(facet, value)`` (the strict
    context filter); right-click → ``tag_discover_clicked(facet, value)``.
    """

    COLLAPSE_KEY = "details"

    tag_filter_clicked = pyqtSignal(str, str)
    tag_discover_clicked = pyqtSignal(str, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._is_live = False
        self._provider_name = ""
        self._copy_label = ""
        self._metadata_from_tmdb = False
        self._release_date = ""
        self._tags: list = []
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._header = CollapsibleHeader("Details")
        self._header_widget = self._header
        layout.addWidget(self._header)

        self._content = QWidget()
        self._body = QVBoxLayout(self._content)
        self._body.setContentsMargins(SECTION_INDENT, 0, 0, 0)
        self._body.setSpacing(6)
        layout.addWidget(self._content)
        self._wire_header()
        self.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_mode(self, is_live: bool) -> None:
        self._is_live = is_live
        self._render()

    def set_copy(self, *, provider_name: str, copy_code: str) -> None:
        """Name the copy on screen: its source (for "From <source>") and its
        prefix code (for the "Details for English (EN)" heading)."""
        self._provider_name = provider_name or "the source"
        self._copy_label = display_code(copy_code, self.config) if copy_code else ""
        self._header.set_title(
            f"Details for {self._copy_label}" if self._copy_label else "Details"
        )

    def load_tags(self, tags: list) -> None:
        """Populate from ``ChannelTagDTO`` objects (never ORM rows)."""
        self._tags = [t for t in tags if t.facet_type not in _TITLE_BLOCK_FACETS]
        self._render()

    def load_metadata(self, metadata) -> None:
        """Take the release date (the one fact Technical Details used to show)."""
        self._release_date = (getattr(metadata, "release_date", None) or "").strip()
        source = (getattr(metadata, "provider_name", None) or "").lower()
        self._metadata_from_tmdb = "tmdb" in source
        self._render()

    def clear(self) -> None:
        self._tags = []
        self._release_date = ""
        self._metadata_from_tmdb = False
        self._render()

    # ------------------------------------------------------------------ #
    # Render                                                               #
    # ------------------------------------------------------------------ #

    def _clear_body(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _region_names(self) -> list[str]:
        codes = sorted({t.value for t in self._tags if t.facet_type == "region"})
        return [display_code(c, self.config) for c in codes]

    def _render(self) -> None:
        self._clear_body()
        # group heading → facet → [(display, facet, value, feeders, guessed)]
        groups: dict[str, dict[str, list]] = {}
        for tag in self._tags:
            heading = group_label(tag.feeders, provider_name=self._provider_name)
            guessed = strongest_kind(tag.feeders) == "inference"
            groups.setdefault(heading, {}).setdefault(tag.facet_type, []).append(
                (self._display(tag.facet_type, tag.value), tag.facet_type, tag.value,
                 tag.feeders, guessed)
            )

        total = sum(len(v) for g in groups.values() for v in g.values())
        if self._release_date:
            heading = "From TMDb" if self._metadata_from_tmdb else f"From {self._provider_name}"
            groups.setdefault(heading, {})["released"] = [
                (self._release_date, None, None, (), False)
            ]
            total += 1

        regions = self._region_names()
        order = GROUP_ORDER(self._provider_name)
        for heading in order + sorted(set(groups) - set(order)):
            if heading in groups:
                self._render_group(heading, groups[heading], regions)

        n = total
        self._header.set_summary(str(n) if n else "", f"{n} fact{'s' * (n != 1)}")
        self._apply_collapsed()
        self.setVisible(not self._is_live and total > 0)

    def _render_group(self, heading: str, facets: dict[str, list], regions: list[str]) -> None:
        head = QLabel(heading.upper())
        _theme.style(head, "DETAIL_GROUP_HEADING")
        self._body.addWidget(head)

        grid_w, grid = make_label_grid(KEY_COL - SECTION_INDENT)
        ordered = [f for f in _FACET_DISPLAY_ORDER if f in facets]
        ordered += sorted(f for f in facets if f not in _FACET_DISPLAY_ORDER)
        for row, facet in enumerate(ordered):
            label = "Released" if facet == "released" else _FACET_LABELS.get(
                facet, facet.replace("_", " ").title())
            grid.addWidget(make_key(label), row, 0, Qt.AlignmentFlag.AlignTop)
            widgets = []
            for display, ftype, value, feeders, guessed in facets[facet]:
                if ftype is None:                       # the release date: a plain fact
                    date = QLabel(display)
                    _theme.style(date, "DETAIL_TEXT")
                    widgets.append(date)
                    continue
                widgets.append(self._make_value_chip(display, ftype, value, guessed))
                if guessed:
                    why = QLabel(guess_reason(feeders, regions))
                    why.setFixedHeight(make_chip("x").sizeHint().height())
                    _theme.style(why, "DETAIL_FACT_REASON")
                    widgets.append(why)
            grid.addWidget(make_flow(widgets), row, 1)
        self._body.addWidget(grid_w)

    def _display(self, facet: str, value: str) -> str:
        if facet == "region":
            return display_code(value, self.config)
        if facet == "content_type":
            return content_type_display(value)
        return value

    def _make_value_chip(self, display: str, facet: str, value: str, guessed: bool):
        # A guess is never facet-tinted: it reads at body text, dashed.
        token = "COLOR_TEXT" if guessed else _facet_colour_token(facet)
        chip = make_chip(display, token, dashed=guessed)
        # Properties + one shared bound slot, never a lambda over self: a
        # closure that captures the widget it is connected on is a reference
        # cycle the top-level-widget leak guard reports.
        chip.setProperty("facet", facet)
        chip.setProperty("value", value)
        chip.clicked.connect(self._on_value_clicked)
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(self._on_value_context)
        hint = ("Click: show this collection's channels" if facet == "collection"
                else "Click: filter to this tag")
        chip.setToolTip(f"{display}\n{hint}  ·  Right-click: Discover this tag")
        return chip

    def _sender_tag(self) -> tuple[str, str] | None:
        chip = self.sender()
        if chip is None:
            return None
        facet, value = chip.property("facet"), chip.property("value")
        return (str(facet), str(value)) if facet and value is not None else None

    def _on_value_clicked(self) -> None:
        tag = self._sender_tag()
        if tag:
            self.tag_filter_clicked.emit(*tag)

    def _on_value_context(self, _pos) -> None:
        tag = self._sender_tag()
        if tag:
            self.tag_discover_clicked.emit(*tag)

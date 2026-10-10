"""The details pane's "Details for <copy>" section (DETAILS-3d).

Every stored fact about the copy on screen, one row per facet under a thin
left rule. Each value is tinted text followed by a quiet caption naming where
it came from ("· TREX Shared", "· TMDb"); a guess is italic and its caption
says why ("· guessed from region Sweden (SE)"). Genre and collection are not
here: both already sit in the title block above.

Facts describe ONE copy. Nothing is merged in from the other copies of the
title: a copy's language, subtitles and audio are its own, and a merged list
would claim the English copy has Swedish audio.

Replaces the old Tags and Technical Details sections; the release date that
Technical carried is a row here.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from metatv.core.channel_name_utils import content_type_display
from metatv.core.stream_info import display_rows, measured_caption, summarize
from metatv.core.tag_provenance import group_label, guess_reason, strongest_kind
from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme
from metatv.gui.qt_text_utils import escape_mnemonic
from metatv.gui.detail_chips import (
    fact_value_sheet,
    make_chip,
    KEY_COL, SECTION_INDENT, display_code, make_flow, make_key, make_label_grid,
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
    "title":       "Alternate title",
    "original_title": "Original title",
}

# Shown in the title block above, never repeated here.
_TITLE_BLOCK_FACETS = frozenset({"genre", "collection", "cast", "director"})


def _source_caption(heading: str) -> str:
    """"From TREX Shared" → "TREX Shared"; "Seen in the file" → "seen in the file"."""
    return heading[5:] if heading.startswith("From ") else heading[0].lower() + heading[1:]


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
    #: "Get stream details" pressed — measure the stream without playing it.
    probe_requested = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._is_live = False
        self._provider_name = ""
        self._copy_label = ""
        self._metadata_from_tmdb = False
        self._release_date = ""
        self._original_language = ""
        self._tags: list = []
        self._stream_rows: list[tuple[str, str]] = []
        self._stream_caption = ""
        self._stream_languages: tuple = ()
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._header = CollapsibleHeader("Details")
        self._header_widget = self._header
        layout.addWidget(self._header)

        self._content = QWidget()
        content_lay = QVBoxLayout(self._content)
        content_lay.setContentsMargins(SECTION_INDENT, 0, 0, 0)
        content_lay.setSpacing(6)
        facts = QWidget()
        self._body = QVBoxLayout(facts)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(6)
        content_lay.addWidget(facts)
        # PLAYED-2: measure the stream on request instead of having to play it.
        self._probe_btn = make_chip("Get stream details")
        self._probe_btn.setToolTip(
            "Open the stream briefly in the background and record its resolution,\n"
            "frame rate, codecs, bitrate and audio/subtitle tracks")
        self._probe_btn.clicked.connect(self.probe_requested)
        self._probe_running = False
        self._probe_available = True
        self._stream_source = ""
        # In the heading, left of the count: an action on the section, not a fact.
        self._header.add_action(self._probe_btn)
        layout.addWidget(self._content)
        self._wire_header()
        self._has_copy = False
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
        self._has_copy = True
        self._probe_running = False

    def load_tags(self, tags: list) -> None:
        """Populate from ``ChannelTagDTO`` objects (never ORM rows)."""
        self._tags = [t for t in tags if t.facet_type not in _TITLE_BLOCK_FACETS]
        self._render()

    def load_metadata(self, metadata) -> None:
        """Take the release date (the one fact Technical Details used to show)."""
        self._release_date = (getattr(metadata, "release_date", None) or "").strip()
        self._original_language = getattr(metadata, "original_language", None) or ""
        source = (getattr(metadata, "provider_name", None) or "").lower()
        self._metadata_from_tmdb = "tmdb" in source
        self._render()

    def load_stream_info(self, record: dict | None, *, claimed_quality: str | None = None) -> None:
        """Show what the stream actually contained when last measured
        (PLAYED-1) — first, above anything the provider claims.

        Args:
            record: ``StreamInfoRepository.get`` output, or None (never measured).
            claimed_quality: The channel's provider-stated quality, so a stream
                that falls short of it says so.
        """
        if record and record.get("info"):
            self._stream_rows = display_rows(record["info"], claimed_quality=claimed_quality)
            self._stream_languages = (summarize(record) or {}).get("audio", ())
            self._stream_caption = measured_caption(record.get("measured_at"), record.get("source", ""))
            self._stream_source = record.get("source", "")
        else:
            self._stream_rows, self._stream_caption = [], ""
            self._stream_languages = ()
            self._stream_source = ""
        self._render()

    def set_original_language(self, language: str) -> None:
        """Show an original language that arrived after the metadata."""
        if language and not self._original_language:
            self._original_language = language
            self._render()

    def clear(self) -> None:
        self._stream_source = ""
        self._stream_rows, self._stream_caption = [], ""
        self._stream_languages = ()
        self._tags = []
        self._release_date = ""
        self._original_language = ""
        self._metadata_from_tmdb = False
        self._has_copy = False   # nothing on screen: no heading, no probe button
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
        """One row per facet under a thin left rule (DETAILS-3e, option D).

        No group headings: each value is tinted text (no box) followed by a
        quiet caption naming where it came from ("· TREX Shared", "· TMDb"),
        or, for a guess, why ("· guessed from region Sweden (SE)").
        """
        self._clear_body()
        # facet → [(display, facet, value, feeders, guessed, caption)]
        rows: dict[str, list] = {}
        regions = self._region_names()
        for tag in self._tags:
            guessed = strongest_kind(tag.feeders) == "inference"
            if guessed and tag.facet_type == "decade":
                # A decade comes from a year WRITTEN in the title ("(2018)"):
                # deduced from it, not guessed.
                guessed, caption = False, "deduced from title"
            elif guessed:
                caption = f"guessed {guess_reason(tag.feeders, regions)}"
            else:
                caption = _source_caption(group_label(tag.feeders,
                                                      provider_name=self._provider_name))
            rows.setdefault(tag.facet_type, []).append(
                (self._display(tag.facet_type, tag.value), tag.facet_type, tag.value, guessed, caption)
            )
        # Languages heard in the stream lead the Language row; anything the
        # provider or the region implies stays below them as lower-priority
        # facts (a |SE| copy can be English audio with Swedish burned-in
        # subtitles — the region guess is still worth keeping).
        if self._stream_languages:
            existing = rows.get("language", [])
            heard = [(lang, "language", lang, False, self._stream_caption)
                     for lang in self._stream_languages]
            rest = [r for r in existing if r[2] not in self._stream_languages]
            # The Audio row already names what was heard; a Language row that
            # only repeats it says nothing new.
            if rest or len(self._stream_languages) > 1:
                rows["language"] = heard + rest
            else:
                rows.pop("language", None)
        heard_only = set(self._stream_languages)
        if self._original_language and heard_only != {self._original_language}:
            # LANG-2: the title's original language — a fact about the film, not
            # about this copy's audio (that is the Language row above).
            rows["original"] = [(self._original_language, None, None, False,
                                 "TMDb" if self._metadata_from_tmdb else "reported by source")]
        if self._release_date:
            rows["released"] = [(self._release_date, None, None, False,
                                 "TMDb" if self._metadata_from_tmdb else self._provider_name)]
        total = sum(len(v) for v in rows.values()) + len(self._stream_rows)

        rule = QWidget()
        rule.setObjectName("detailsRule")
        rule.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        _theme.style(rule, "DETAIL_FACTS_RULE")
        rule_lay = QVBoxLayout(rule)
        rule_lay.setContentsMargins(12, 2, 0, 2)
        grid_w, grid = make_label_grid(KEY_COL - SECTION_INDENT - 14)
        grid.setVerticalSpacing(3)
        ordered = [f for f in _FACET_DISPLAY_ORDER if f in rows]
        tail = ("original", "released")
        ordered += sorted(f for f in rows if f not in _FACET_DISPLAY_ORDER and f not in tail)
        ordered += [f for f in tail if f in rows]
        # Measured rows first: what the stream really is outranks any claim.
        for r, (key, text) in enumerate(self._stream_rows):
            if key:
                grid.addWidget(make_key(key), r, 0, Qt.AlignmentFlag.AlignTop)
            value = QLabel(text)
            _theme.style(value, "DETAIL_TEXT")
            widgets = [value]
            if r == 0:
                cap = QLabel(f"· {self._stream_caption}")
                _theme.style(cap, "DETAIL_FACT_REASON")
                widgets.append(cap)
            grid.addWidget(make_flow(widgets), r, 1)
        offset = len(self._stream_rows)
        for r, facet in enumerate(ordered, start=offset):
            label = {"released": "Released", "original": "Original language"}.get(
                facet) or _FACET_LABELS.get(
                facet, facet.replace("_", " ").title())
            grid.addWidget(make_key(label), r, 0, Qt.AlignmentFlag.AlignTop)
            widgets = []
            for display, ftype, value, guessed, caption in rows[facet]:
                if ftype is None:                       # the release date: a plain fact
                    date = QLabel(display)
                    _theme.style(date, "DETAIL_TEXT")
                    widgets.append(date)
                else:
                    widgets.append(self._make_value_chip(display, ftype, value, guessed))
                cap = QLabel(f"· {caption}")
                _theme.style(cap, "DETAIL_FACT_REASON")
                widgets.append(cap)
            grid.addWidget(make_flow(widgets), r, 1)
        rule_lay.addWidget(grid_w)
        if total:
            self._body.addWidget(rule)
        else:
            rule.deleteLater()

        n = total
        self._header.set_summary(str(n) if n else "", f"{n} fact{'s' * (n != 1)}")
        self._apply_collapsed()
        # Always shown once a copy is on screen: even with no facts yet, the
        # "Get stream details" button is what fills it.
        self.setVisible(self._has_copy)
        self._sync_probe_button()

    def set_probe_available(self, available: bool) -> None:
        """Hide the probe button where there is no stream to measure (a series
        root — only its episodes are streams)."""
        self._probe_available = available
        self._sync_probe_button()

    def set_probe_running(self, running: bool) -> None:
        """Show the probe as in progress (disabled, "Checking stream…") or idle."""
        self._probe_running = running
        self._sync_probe_button()

    def _sync_probe_button(self) -> None:
        if self._probe_running:
            text = "Checking stream…"
        else:
            # "Re-check" only once WE measured it; a source's report was never checked.
            checked = self._stream_source in ("played", "probe")
            text = "Re-check stream" if checked else "Get stream details"
        self._probe_btn.setText(text)
        self._probe_btn.setEnabled(not self._probe_running)
        self._probe_btn.setVisible(self._probe_available)

    def _display(self, facet: str, value: str) -> str:
        if facet == "region":
            return display_code(value, self.config)
        if facet == "content_type":
            return content_type_display(value)
        return value

    def _make_value_chip(self, display: str, facet: str, value: str, guessed: bool):
        # A guess is never facet-tinted: it reads at body text, dashed.
        token = "COLOR_TEXT" if guessed else _facet_colour_token(facet)
        chip = QPushButton(escape_mnemonic(display))
        chip.setFlat(True)
        _theme.style_fn(chip, lambda: fact_value_sheet(token, guessed=guessed))
        cursor_affordance.set_clickable(chip)
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

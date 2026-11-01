"""The Sources editor's Analytics tab — is this source worth keeping, and how does it behave.

Replaces the separate Source Analytics screen (owner's design, 2026-10-20,
artifact "Source Analytics Tab", every recommendation accepted 2026-10-31;
re-laid out for width 2026-10-31, same artifact). Top to bottom:

* **Figure tiles** — the headline numbers that used to sit inside sentences:
  titles only here (with Browse, Q5), films / series / live, guide coverage,
  days left, plays that started, the connection limit.
* **Two columns of cards** — left: What you watch here, Shared with your other
  sources (one row per source, a short bar per media type; disabled and
  expired sources greyed and labelled, Q9; redundancy hint, Q10), Server
  addresses (the ones that worked; the rest behind Show all). Right: Playback
  (Q6; failures by time of day, Q11, ``gui/hour_strip.py``) and Connections
  (Q7, ``gui/connection_wait.py``). One column below ``TWO_COLUMNS_FROM`` px.
* **Titles by region** — every region, three across, the first rows shown and
  the rest behind Show all (region is how these catalogues label language).
* **Unrecognized prefixes** — the parser's worklist, live / films / series side
  by side, last because it is a worklist rather than a verdict (Q2).

Nothing is cut off: every list longer than it shows has a Show all that
expands it in place. Bars are short and fixed-width, so a 5% row is not a
page-wide empty track.

"The same title" is the stored ``content_key`` across live, films and series
(Q3). Everything loads off-thread through the host's ``run_query`` seam when
the tab opens, each card filling in as it arrives; the title overlap — the one
slow read, ~3 s on the owner's library — is cached for the session (Q12).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from metatv.core.region_codes import REGION_FULL_NAMES
from metatv.core.repositories.dtos import (
    CatalogueMixDTO, ConnectionsDTO, GuideCoverageDTO, PlaybackSummaryDTO, PrefixStatDTO, ServerAddressDTO,
    TitleOverlapDTO, ViewingDTO,
)
from metatv.core.time_display import short_date_text
from metatv.gui import cursor_affordance, icons
from metatv.gui import theme as _theme
from metatv.gui.connection_wait import minutes_text
from metatv.gui.chip_row import MiddleElideLabel
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.hour_strip import HourStrip, struggle_span
from metatv.gui.progress_paint import ProgressBar
from metatv.gui.tool_view import clear_layout, show_loading, show_panel_error

#: (media_type, plural noun) in the order every section lists them.
MEDIA = (("movie", "films"), ("series", "series"), ("live", "live channels"))

#: Column headings for the per-media-type columns (Shared).
MEDIA_HEADING = {"movie": "Films", "series": "Series", "live": "Live"}

#: Another source carrying at least this share of a source's films and series
#: earns the redundancy hint. Advisory only: nothing is hidden (Q10).
REDUNDANT_AT = 0.95

#: Plays recorded before the time-of-day strip is drawn (Q11: "once there is
#: data") — fewer and one bad evening reads as a pattern.
MIN_PLAYS_BY_HOUR = 30

#: Below this share of live channels with guide data the tile says "low".
LOW_GUIDE_SHARE = 0.25

#: Figure tiles per row, equal widths.
TILES_ACROSS = 4

#: Width at which the cards sit in two columns; narrower, they stack.
TWO_COLUMNS_FROM = 860

#: Rows shown before Show all — regions, prefixes per type, most played.
REGION_ROWS = 5
PREFIX_ROWS = 10
TOP_ROWS = 5

#: Regions per row: three in the two-column layout, two when the cards stack
#: (three across at 760 px elided "France (FR)" to "Fr…R)", Q20).
REGIONS_ACROSS_WIDE = 3
REGIONS_ACROSS_NARROW = 2

#: Media type → the singular noun a Most played row shows.
MEDIA_SINGULAR = {"movie": "film", "series": "series", "live": "live"}

#: A short bar: long enough to compare, too short to be a page-wide empty track.
BAR_PX = 56


def source_state_label(name: str, is_active: bool, is_expired: bool) -> str:
    """A source's name with its state, so a greyed row also SAYS why (color never alone)."""
    if is_expired:
        return f"{name} (expired)"
    if not is_active:
        return f"{name} (disabled)"
    return name


def redundancy_hint(overlap: TitleOverlapDTO, provider_id: str) -> str | None:
    """"X carries almost everything Y does" when some source shares ≥ 95% of Y's
    films and series combined, else None. The highest-sharing source wins."""
    names = {s.id: s.name for s in overlap.sources}
    mine = sum(overlap.totals.get((provider_id, m), 0) for m in ("movie", "series"))
    if not mine:
        return None
    best = max(
        ((sum(overlap.shared.get((provider_id, s.id, m), 0) for m in ("movie", "series")), s.id)
         for s in overlap.sources if s.id != provider_id),
        default=(0, None),
    )
    if best[1] is None or best[0] / mine < REDUNDANT_AT:
        return None
    return (f"{names[best[1]]} carries almost everything {names[provider_id]} does — "
            "one of the two is probably redundant.")


def _label(text: str, role: str) -> QLabel:
    label = QLabel(text)
    _theme.style(label, role)
    return label


class _Section(QFrame):
    """A card: a heading with a right-aligned subtitle over a body that loads on its own."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsCard")
        _theme.style(self, "ANALYTICS_CARD")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(6)
        head = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setWordWrap(True)
        _theme.style(self.title, "SECTION_TITLE_SM")
        head.addWidget(self.title, 1)
        self.subtitle = QLabel("")
        _theme.style(self.subtitle, "META_HINT")
        head.addWidget(self.subtitle)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(4)
        outer.addLayout(self.body)

    def text(self, html_text: str, role: str = "SECTION_HINT") -> QLabel:
        label = QLabel(html_text)
        label.setWordWrap(True)
        _theme.style(label, role)
        self.body.addWidget(label)
        return label

    def grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.body.addLayout(grid)
        return grid

    def show_all(self, hidden: list[QWidget], total: int) -> None:
        """Hide *hidden* behind a "Show all (N)" toggle that expands in place."""
        if not hidden:
            return
        for widget in hidden:
            widget.setVisible(False)
        more = f"{icons.show_all_icon} Show all ({total:,})"
        button = QPushButton(more)
        button.setToolTip(f"Show all {total:,} — {len(hidden):,} more rows")
        _theme.style(button, "LINK_BTN_SM")
        cursor_affordance.set_clickable(button)

        def toggle() -> None:
            opening = button.text() == more
            for widget in hidden:
                widget.setVisible(opening)
            button.setText("Show fewer" if opening else more)

        button.clicked.connect(toggle)
        row = QHBoxLayout()
        row.addWidget(button)
        row.addStretch(1)
        self.body.addLayout(row)


class _Tile(QFrame):
    """One headline figure over its caption; hidden until its query answers."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsCard")
        _theme.style(self, "ANALYTICS_CARD")
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 8, 16, 10)
        box.setSpacing(0)
        self.figure = _label("", "STAT_FIGURE")
        box.addWidget(self.figure)
        self.caption = _label("", "META_HINT")
        self.caption.setWordWrap(True)
        box.addWidget(self.caption)
        box.addStretch(1)
        self.hide()

    def set(self, figure: str, caption: str, *, warn: bool = False) -> None:
        self.figure.setText(figure)
        _theme.style(self.figure, "STAT_FIGURE_WARN" if warn else "STAT_FIGURE")
        self.caption.setText(caption)
        self.show()


def _facts(section: _Section, facts) -> None:
    """Caption · figure pairs that wrap as a flow — Playback and What you watch."""
    holder = QWidget()
    flow = FlowLayout(holder, h_spacing=24, v_spacing=6)
    flow.setContentsMargins(0, 0, 0, 0)
    for caption, value in facts:
        pair = QWidget()
        row = QHBoxLayout(pair)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_label(caption, "META_HINT"))
        row.addWidget(_label(value, "FIELD_LABEL"))
        flow.addWidget(pair)
    section.body.addWidget(holder)


class _LinkLabel(MiddleElideLabel):
    """A middle-eliding label that is clicked like a link (region names, Q18)."""

    clicked = pyqtSignal()

    def __init__(self, text: str, tooltip: str) -> None:
        super().__init__(text, color_token="COLOR_LINK")
        self.setToolTip(tooltip)
        cursor_affordance.set_clickable(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _bar(fraction: float | None) -> ProgressBar:
    return ProgressBar((fraction or 0.0) * 100.0, width=BAR_PX, height=6, warn_at=None)


class SourceAnalyticsTab(QWidget):
    """The Analytics tab body. ``show_provider(id)`` (re)loads it for one source."""

    #: ("Only on <source>", channel ids) — the host opens Search on them (Q5).
    browse_requested = pyqtSignal(str, object)

    def __init__(self, run_query: Callable, parent=None) -> None:
        super().__init__(parent)
        self._run_query = run_query
        self._provider_id: str | None = None
        self._overlap: TitleOverlapDTO | None = None
        self._mix: CatalogueMixDTO | None = None
        self._source_name = ""
        self._regions_across = REGIONS_ACROSS_WIDE
        # One token per query type (the seam's contract): these load together
        # and must not supersede one another; a provider switch bumps them all.
        self._tokens = {k: [0] for k in ("overlap", "viewing", "playback", "connections", "catalogue", "addresses",
                                         "prefixes", "region")}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)
        self._empty = QLabel("Save the source first — there is nothing to analyse yet.")
        _theme.style(self._empty, "SECTION_HINT")
        layout.addWidget(self._empty)
        self._empty.hide()

        self._tiles_box = QWidget()
        tiles = QGridLayout(self._tiles_box)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(10)
        self._tiles = {k: _Tile() for k in ("only", "movie", "series", "live", "guide", "days", "started", "limit")}
        for i, tile in enumerate(self._tiles.values()):
            tiles.addWidget(tile, *divmod(i, TILES_ACROSS))
        for col in range(TILES_ACROSS):
            tiles.setColumnStretch(col, 1)
        self._browse = QPushButton("Browse them")
        _theme.style(self._browse, "LINK_BTN_SM")
        cursor_affordance.set_clickable(self._browse)
        self._browse.clicked.connect(self._emit_browse)
        browse_row = QHBoxLayout()
        browse_row.addWidget(self._browse)
        browse_row.addStretch(1)
        self._tiles["only"].layout().insertLayout(2, browse_row)
        self._browse_ids: tuple[str, frozenset[str]] | None = None
        layout.addWidget(self._tiles_box)

        self._viewing = _Section("What you watch here")
        self._shared = _Section("Shared with your other sources")
        self._addresses = _Section("Server addresses")
        self._playback = _Section("Playback")
        self._connections = _Section("Connections")
        self._catalogue = _Section("Titles by region")
        self._prefixes = _Section("Unrecognized prefixes")

        self._columns = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._columns.setSpacing(12)
        for cards in ((self._viewing, self._shared), (self._playback, self._connections, self._addresses)):
            column = QVBoxLayout()
            column.setSpacing(12)
            for card in cards:
                column.addWidget(card)
            column.addStretch(1)
            self._columns.addLayout(column, 1)
        layout.addLayout(self._columns)
        layout.addWidget(self._catalogue)
        layout.addWidget(self._prefixes)
        layout.addStretch(1)
        self._shared.subtitle.setText("same title, by title identity")

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(event)
        wide = event.size().width() >= TWO_COLUMNS_FROM
        self._columns.setDirection(QBoxLayout.Direction.LeftToRight if wide
                                   else QBoxLayout.Direction.TopToBottom)
        across = REGIONS_ACROSS_WIDE if wide else REGIONS_ACROSS_NARROW
        if across != self._regions_across:
            self._regions_across = across
            if self._mix is not None:
                self._render_regions(self._mix)

    # ── Loading ─────────────────────────────────────────────────────────────

    def show_provider(self, provider_id: str | None) -> None:
        """Load (or re-render) the tab for *provider_id*; None = an unsaved source."""
        self.deactivate()
        self._provider_id = provider_id
        self._mix = None
        sections = self._sections()
        self._empty.setVisible(provider_id is None)
        self._tiles_box.setVisible(provider_id is not None)
        for tile in self._tiles.values():
            tile.hide()
        self._browse.hide()
        for section in sections:
            section.setVisible(provider_id is not None)
        if provider_id is None:
            return
        for section in sections:
            show_loading(section.body)

        if self._overlap is not None:
            self._render_overlap(self._overlap)
        else:
            self._run_query(lambda repos: repos.analytics.title_overlap(), self._on_overlap,
                            token_ref=self._tokens["overlap"],
                            on_error=lambda e: show_panel_error(self._shared.body, e))
        pid = provider_id
        self._run_query(lambda repos: repos.analytics.viewing(pid), self._on_viewing,
                        token_ref=self._tokens["viewing"],
                        on_error=lambda e: show_panel_error(self._viewing.body, e))
        self._run_query(lambda repos: repos.playback_events.summary(pid), self._on_playback,
                        token_ref=self._tokens["playback"],
                        on_error=lambda e: show_panel_error(self._playback.body, e))
        self._run_query(lambda repos: repos.playback_events.connections(pid), self._on_connections,
                        token_ref=self._tokens["connections"],
                        on_error=lambda e: show_panel_error(self._connections.body, e))
        self._run_query(lambda repos: (repos.analytics.guide_coverage(pid),
                                       repos.providers.get_by_id(pid).account_exp_date,
                                       repos.analytics.catalogue_mix(pid)),
                        self._on_catalogue, token_ref=self._tokens["catalogue"],
                        on_error=lambda e: show_panel_error(self._catalogue.body, e))
        self._run_query(lambda repos: repos.analytics.server_addresses(pid), self._on_addresses,
                        token_ref=self._tokens["addresses"],
                        on_error=lambda e: show_panel_error(self._addresses.body, e))
        self._run_query(lambda repos: repos.analytics.unrecognized_prefixes(pid), self._on_prefixes,
                        token_ref=self._tokens["prefixes"],
                        on_error=lambda e: show_panel_error(self._prefixes.body, e))

    def _sections(self) -> tuple[_Section, ...]:
        """Reading order: left column (what it carries), right column (how it
        behaves), then the full-width cards (Q2)."""
        return (self._viewing, self._shared, self._playback, self._connections, self._addresses,
                self._catalogue, self._prefixes)

    def deactivate(self) -> None:
        """Drop every in-flight result (tab left, source switched, editor closed)."""
        for ref in self._tokens.values():
            ref[0] += 1

    def forget_cached_overlap(self) -> None:
        """The catalogue changed (a refresh finished): recompute on next open."""
        self._overlap = None

    def _emit_browse(self) -> None:
        if self._browse_ids:
            self.browse_requested.emit(*self._browse_ids)

    # ── Tiles + Shared ──────────────────────────────────────────────────────

    def _on_overlap(self, overlap: TitleOverlapDTO) -> None:
        self._overlap = overlap
        self._render_overlap(overlap)

    def _render_overlap(self, overlap: TitleOverlapDTO) -> None:
        pid = self._provider_id
        me = next((s for s in overlap.sources if s.id == pid), None)
        if me is None:
            return
        others = [s for s in overlap.sources if s.id != pid]
        self._source_name = me.name
        only = {m: overlap.only.get((pid, m), 0) for m, _ in MEDIA}
        totals = {m: overlap.totals.get((pid, m), 0) for m, _ in MEDIA}

        for media, noun in MEDIA:
            self._tiles[media].set(f"{totals[media]:,}", noun)
        ids = overlap.only_ids.get(pid, frozenset())
        if others:
            self._tiles["only"].set(f"{sum(only.values()):,}", f"titles only on {me.name}")
            self._browse_ids = (f"Only on {me.name}", ids)
            self._browse.setToolTip(f"Show the {len(ids):,} channels only {me.name} carries in Search")
            self._browse.setVisible(bool(ids))
        else:
            self._tiles["only"].set(f"{sum(totals.values()):,}", "titles — your only source")
            self._browse.setVisible(False)

        clear_layout(self._shared.body)
        if not others:
            self._shared.text("No other sources to compare with.")
            return
        grid = self._shared.grid()
        shown = [m for m, _ in MEDIA if totals[m]]
        for col, media in enumerate(shown, start=1):
            grid.addWidget(_label(MEDIA_HEADING[media], "META_HINT"), 0, col)
        grid.setColumnStretch(0, 1)
        for row, other in enumerate(others, start=1):
            muted = other.is_expired or not other.is_active
            name = QLabel(source_state_label(other.name, other.is_active, other.is_expired))
            name.setWordWrap(True)
            _theme.style(name, "LABEL_MUTED" if muted else "SECTION_HINT")
            grid.addWidget(name, row, 0)
            for col, media in enumerate(shown, start=1):
                total, both = totals[media], overlap.shared.get((pid, other.id, media), 0)
                cell = QWidget()
                cell.setToolTip(f"{other.name} also carries {both:,} of this source's "
                                f"{total:,} {dict(MEDIA)[media]}")
                box = QHBoxLayout(cell)
                box.setContentsMargins(0, 0, 0, 0)
                box.setSpacing(6)
                box.addWidget(_label(f"{both / total:.0%}", "LABEL_MUTED" if muted else "FIELD_LABEL"))
                box.addWidget(_bar(both / total))
                grid.addWidget(cell, row, col)
        hint = redundancy_hint(overlap, pid)
        if hint:
            self._shared.text(hint)

    # ── Catalogue: guide + days tiles, regions card ─────────────────────────

    def _on_catalogue(self, result: tuple[GuideCoverageDTO, datetime | None, CatalogueMixDTO]) -> None:
        guide, expires, mix = result
        if guide.live_channels:
            share = guide.with_guide / guide.live_channels
            low = share < LOW_GUIDE_SHARE
            self._tiles["guide"].set(f"{share:.1%}", "of live channels have guide data"
                                     + (" — low" if low else ""), warn=low)
            self._tiles["guide"].setToolTip(
                f"{guide.with_guide:,} of {guide.live_channels:,} live channels"
                + (f"; guide runs through {short_date_text(guide.guide_until)}" if guide.guide_until else ""))
        if expires is not None:
            days = (expires - datetime.now()).days
            if days < 0:
                self._tiles["days"].set("Expired", f"on {short_date_text(expires)}", warn=True)
            else:
                self._tiles["days"].set(f"{days}", "days left", warn=days <= 7)
        self._mix = mix
        self._render_regions(mix)

    def _render_regions(self, mix: CatalogueMixDTO) -> None:
        clear_layout(self._catalogue.body)
        across = self._regions_across
        tail = [f"{len(mix.regions):,} regions"] if mix.regions else []
        if mix.unknown:
            tail.append(f"{mix.unknown:,} titles with no region")
        self._catalogue.subtitle.setText(" · ".join(tail))
        if not mix.total:
            self._catalogue.text("No titles yet.")
            return
        if not mix.regions:
            self._catalogue.text("No region detected on any title.", "META_HINT")
            return
        grid = self._catalogue.grid()
        hidden: list[QWidget] = []
        per = 4  # name · bar · percent · titles
        for i, (code, n) in enumerate(mix.regions):
            row, group = divmod(i, across)
            name = REGION_FULL_NAMES.get(code, code)
            label = name if name == code else f"{name} ({code})"
            link = _LinkLabel(label, f"Browse the {n:,} titles in {name} on this source")
            link.clicked.connect(lambda c=code, lbl=name: self._browse_region(c, lbl))
            cells = (link, _bar(n / mix.total), _label(f"{n / mix.total:.0%}", "FIELD_LABEL"),
                     _label(f"{n:,}", "META_HINT"))
            for j, widget in enumerate(cells):
                grid.addWidget(widget, row, group * (per + 1) + j)
            if row >= REGION_ROWS:
                hidden.extend(cells)
        for group in range(across):
            grid.setColumnStretch(group * (per + 1) + per, 1)    # slack after each group

        self._catalogue.show_all(hidden, len(mix.regions))

    def _browse_region(self, code: str, name: str) -> None:
        """A region was clicked: hand its channels on this source to Search (Q18)."""
        pid, source = self._provider_id, self._source_name or "this source"
        if pid is None:
            return
        self._run_query(lambda repos: repos.analytics.region_channel_ids(pid, code),
                        lambda ids: self.browse_requested.emit(f"{name} on {source}", ids),
                        token_ref=self._tokens["region"],
                        on_error=lambda e: show_panel_error(self._catalogue.body, e))

    # ── Cards ───────────────────────────────────────────────────────────────

    def _on_viewing(self, viewing: ViewingDTO) -> None:
        clear_layout(self._viewing.body)
        self._viewing.subtitle.setText(
            f"last played {short_date_text(viewing.last_played)}" if viewing.last_played else "")
        if not viewing.plays:
            self._viewing.text("Nothing played from this source yet.")
            return
        kinds = " · ".join(f"{viewing.by_media[m]:,} {noun}" for m, noun in MEDIA
                           if viewing.by_media.get(m))
        if viewing.seconds_watched:
            watched = f"{viewing.seconds_watched / 3600:.1f} h"
            if viewing.watched_since:
                watched += f" since {short_date_text(viewing.watched_since)}"
        else:
            watched = "counted from now on"
        facts = [
            ("Titles played", f"{viewing.titles:,} ({kinds})" if kinds else f"{viewing.titles:,}"),
            ("Plays", f"{viewing.plays:,}"),
            ("Time watched", watched),
            ("Played in the last 30 days", f"{viewing.recent:,} titles"),
        ]
        if viewing.episodes:
            facts.append(("Episodes", f"{viewing.episodes:,} across {viewing.episode_series:,} series"))
        if viewing.favourites:
            facts.append(("Favourites here", f"{viewing.favourites:,}"))
        _facts(self._viewing, facts)
        if viewing.only_here:
            self._viewing.text(f"<b>{viewing.only_here:,}</b> of the {viewing.titles:,} titles you've "
                               "played are on no other source — you'd lose them without it.")
        if viewing.top:
            self._viewing.body.addWidget(_label("Most played", "LABEL_MUTED"))
            grid = self._viewing.grid()
            grid.setColumnStretch(4, 1)       # the row hugs its title; slack goes last
            hidden: list[QWidget] = []
            for row, (title, media, plays, when) in enumerate(viewing.top):
                cells = (MiddleElideLabel(title), _label(MEDIA_SINGULAR.get(media, media), "META_HINT"),
                         _label(f"{plays:,} plays" if plays != 1 else "1 play", "FIELD_LABEL"),
                         _label(short_date_text(when) if when else "", "META_HINT"))
                for col, widget in enumerate(cells):
                    grid.addWidget(widget, row, col)
                if row >= TOP_ROWS:
                    hidden.extend(cells)
            self._viewing.show_all(hidden, len(viewing.top))

    def _on_playback(self, summary: PlaybackSummaryDTO) -> None:
        clear_layout(self._playback.body)
        if not summary.attempts:
            self._playback.subtitle.setText("")
            self._playback.text("Nothing recorded yet — plays from this source are counted "
                                "from now on.")
            return
        self._tiles["started"].set(f"{summary.started / summary.attempts:.0%}",
                                   f"of plays started ({summary.started:,} of {summary.attempts:,})",
                                   warn=summary.started / summary.attempts < 0.8)
        self._playback.subtitle.setText(f"since {short_date_text(summary.since)}" if summary.since else "")
        ttp = summary.median_time_to_picture_ms
        _facts(self._playback, (
            ("Never loaded", f"{summary.never_started:,}"),
            ("Refused — connections in use", f"{summary.refused:,}"),
            ("Dropped while playing", f"{summary.dropped:,}"),
            ("Time to picture", f"{ttp / 1000:.1f} s typical" if ttp else "not recorded yet"),
        ))
        self._render_time_of_day(summary)

    def _render_time_of_day(self, summary: PlaybackSummaryDTO) -> None:
        """Failures by local hour (Q11), once enough plays exist to show a pattern."""
        if summary.attempts < MIN_PLAYS_BY_HOUR:
            self._playback.text(f"Failures by time of day: shown once {MIN_PLAYS_BY_HOUR} plays "
                                f"are recorded ({summary.attempts:,} so far).", "META_HINT")
            return
        span = struggle_span(summary.by_hour)
        verdict = f"struggles {span}" if span else "no hour stands out"
        self._playback.text(f"Failures by time of day — {verdict}")
        self._playback.body.addWidget(HourStrip(summary.by_hour))

    def _on_connections(self, conns: ConnectionsDTO) -> None:
        clear_layout(self._connections.body)
        if conns.limit:
            in_use = f" · {conns.in_use} in use at the last check" if conns.in_use is not None else ""
            self._tiles["limit"].set(f"{conns.limit}", "connection at a time" if conns.limit == 1
                                     else "connections at a time")
            self._connections.subtitle.setText(f"{conns.limit} at a time{in_use}")
        else:
            self._connections.subtitle.setText("limit not reported by the source")
        if not conns.waits:
            self._connections.text("No waits yet. When the source refuses a play because its "
                                   "connections are in use, MetaTV waits for one, starts the "
                                   "title, and records how long it took.", "META_HINT")
            return
        _facts(self._connections, (
            ("Usually frees up within", minutes_text(conns.median_seconds)),
            ("Longest wait", minutes_text(conns.longest_seconds)),
            ("Waits recorded", f"{conns.waits:,}"),
        ))

    def _on_addresses(self, addresses: list[ServerAddressDTO]) -> None:
        clear_layout(self._addresses.body)
        worked = sum(1 for a in addresses if a.worked)
        self._addresses.subtitle.setText(f"{worked} of {len(addresses)} have worked")
        if not addresses:
            self._addresses.text("No addresses.")
            return
        grid = self._addresses.grid()
        grid.setColumnStretch(4, 1)
        keep = max(worked, 3)                         # best first: the ones that worked
        hidden: list[QWidget] = []
        for row, a in enumerate(addresses):
            host = MiddleElideLabel(urlparse(a.url).netloc or a.url)
            if a.tried:
                share = a.worked / a.tried
                cells = (host, _bar(share), _label(f"{share:.0%}", "FIELD_LABEL"),
                         _label(f"{a.median_latency_ms / 1000:.1f} s" if a.median_latency_ms else "—",
                                "META_HINT"))
                host.setToolTip(f"{a.url}\n{a.worked} of the last {a.tried} requests worked")
            else:
                cells = (host, _bar(None), _label("—", "LABEL_MUTED"), _label("untested", "META_HINT"))
            for col, widget in enumerate(cells):
                grid.addWidget(widget, row, col)
            if row >= keep:
                hidden.extend(cells)
        self._addresses.show_all(hidden, len(addresses))

    def _on_prefixes(self, prefixes: list[PrefixStatDTO]) -> None:
        clear_layout(self._prefixes.body)
        distinct = len({p.prefix for p in prefixes})
        self._prefixes.subtitle.setText(f"{distinct:,} the name parser does not know")
        if not prefixes:
            self._prefixes.text("Every prefix on this source is recognised.")
            return
        groups: dict[str, list[PrefixStatDTO]] = {}
        for stat in prefixes:  # already live → films → series, commonest first
            groups.setdefault(stat.media_type, []).append(stat)
        nouns = dict(MEDIA)
        across = QHBoxLayout()
        across.setSpacing(24)
        hidden: list[QWidget] = []
        for media, stats in groups.items():
            column = QVBoxLayout()
            column.setSpacing(4)
            column.addWidget(_label(f"{nouns.get(media, 'other').capitalize()} · {len(stats):,}",
                                    "LABEL_MUTED"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(4)
            grid.setColumnStretch(2, 1)
            for row, stat in enumerate(stats):
                code = _label(stat.prefix, "FIELD_LABEL")
                count = _label(f"{stat.count:,}", "META_HINT")
                sample = MiddleElideLabel(stat.sample_names[0] if stat.sample_names else "",
                                          color_token="COLOR_MUTED_2")
                sample.setToolTip("\n".join(stat.sample_names))
                for col, widget in enumerate((code, count, sample)):
                    grid.addWidget(widget, row, col)
                if row >= PREFIX_ROWS:
                    hidden.extend((code, count, sample))
            column.addLayout(grid)
            column.addStretch(1)
            across.addLayout(column, 1)
        self._prefixes.body.addLayout(across)
        self._prefixes.show_all(hidden, distinct)

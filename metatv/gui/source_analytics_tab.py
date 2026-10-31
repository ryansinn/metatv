"""The Sources editor's Analytics tab — is this source worth keeping, and how does it behave.

Replaces the separate Source Analytics screen (owner's design, 2026-10-20,
artifact "Source Analytics Tab", every recommendation accepted 2026-10-31).
Sections, in the order that answers the question first:

* **Only here** — titles no other source carries, with a Browse link (Q5).
* **Shared with your other sources** — per source and media type, how much of
  this source another one also carries, plus a redundancy hint (Q10).
  Disabled and expired sources stay in, greyed and labelled (Q9).
* **Playback** — how plays from this source went: started, never loaded,
  refused at the connection limit, dropped mid-play, time to picture (Q6).
  Recorded by ``gui/playback_start_watch.py`` from 2026-10-31 on.
* **Server addresses** — each address's recent success rate and speed.
* **Catalogue & guide** — titles per type, guide coverage, how far ahead (Q4).
* **Unrecognized prefixes** — the parser's worklist, last because it is a
  worklist rather than a verdict (Q2).

"The same title" is the stored ``content_key`` across live, films and series
(Q3). Everything loads off-thread through the host's ``run_query`` seam when
the tab opens, each section filling in as it arrives; the title overlap — the
one slow read, ~3 s on the owner's library — is cached for the session (Q12).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from urllib.parse import urlparse

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from metatv.core.repositories.dtos import (
    GuideCoverageDTO, PlaybackSummaryDTO, PrefixStatDTO, ServerAddressDTO, TitleOverlapDTO,
)
from metatv.core.time_display import short_date_text
from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme
from metatv.gui.chip_row import MiddleElideLabel
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.progress_paint import ProgressBar
from metatv.gui.tool_view import clear_layout, show_loading, show_panel_error

#: (media_type, plural noun) in the order every section lists them.
MEDIA = (("movie", "films"), ("series", "series"), ("live", "live channels"))

#: The shorter noun a Shared row uses after the source's name.
SHORT_NOUN = {"movie": "films", "series": "series", "live": "live"}

#: Another source carrying at least this share of a source's films and series
#: earns the redundancy hint. Advisory only: nothing is hidden (Q10).
REDUNDANT_AT = 0.95

#: Rows shown before "+ N more" — prefixes, and addresses (best first).
PREFIX_ROWS = 12
ADDRESS_ROWS = 8


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


def _count_line(counts: dict[str, int]) -> str:
    return " · ".join(f"<b>{counts.get(m, 0):,}</b> {noun}" for m, noun in MEDIA)


class _Section(QWidget):
    """A heading with a right-aligned subtitle over a body that loads on its own."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
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

    def text(self, html: str, role: str = "SECTION_HINT") -> QLabel:
        label = QLabel(html)
        label.setWordWrap(True)
        _theme.style(label, role)
        self.body.addWidget(label)
        return label

    def grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        return grid


def _bar_row(grid: QGridLayout, row: int, label: str, fraction: float | None,
             pct_text: str, detail: str, *, muted: bool = False) -> None:
    """Label · bar · percent · detail — the one row shape Shared and Addresses use."""
    name = QLabel(label)
    name.setWordWrap(True)
    _theme.style(name, "LABEL_MUTED" if muted else "SECTION_HINT")
    grid.addWidget(name, row, 0)
    grid.addWidget(ProgressBar((fraction or 0.0) * 100.0, height=6, warn_at=None), row, 1)
    pct = QLabel(pct_text)
    _theme.style(pct, "LABEL_MUTED" if muted else "FIELD_LABEL")
    grid.addWidget(pct, row, 2)
    info = QLabel(detail)
    _theme.style(info, "META_HINT")
    grid.addWidget(info, row, 3)


class SourceAnalyticsTab(QWidget):
    """The Analytics tab body. ``show_provider(id)`` (re)loads it for one source."""

    #: ("Only on <source>", channel ids) — the host opens Search on them (Q5).
    browse_requested = pyqtSignal(str, object)

    def __init__(self, run_query: Callable, parent=None) -> None:
        super().__init__(parent)
        self._run_query = run_query
        self._provider_id: str | None = None
        self._overlap: TitleOverlapDTO | None = None
        # Catalogue needs two reads (overlap totals + guide); it renders once both are in.
        self._catalogue_counts: dict[str, int] | None = None
        self._guide: GuideCoverageDTO | None = None
        self._expires: datetime | None = None
        # One token per query type (the seam's contract): these load together
        # and must not supersede one another; a provider switch bumps them all.
        self._tokens = {k: [0] for k in ("overlap", "playback", "catalogue", "addresses", "prefixes")}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        self._only = _Section("Only on this source")
        self._shared = _Section("Shared with your other sources")
        self._playback = _Section("Playback")
        self._addresses = _Section("Server addresses")
        self._catalogue = _Section("Catalogue & guide")
        self._prefixes = _Section("Unrecognized prefixes")
        sections = self._sections()
        for i, section in enumerate(sections):
            if i:
                line = QFrame()
                line.setFixedHeight(1)
                _theme.style(line, "SEPARATOR_H")
                layout.addWidget(line)
            layout.addWidget(section)
        layout.addStretch(1)
        self._only.subtitle.setText("what you'd lose without it")
        self._shared.subtitle.setText("same title, by title identity")
        self._empty = QLabel("Save the source first — there is nothing to analyse yet.")
        _theme.style(self._empty, "SECTION_HINT")
        layout.insertWidget(0, self._empty)
        self._empty.hide()

    # ── Loading ─────────────────────────────────────────────────────────────

    def show_provider(self, provider_id: str | None) -> None:
        """Load (or re-render) the tab for *provider_id*; None = an unsaved source."""
        self.deactivate()
        self._provider_id = provider_id
        self._catalogue_counts = self._guide = self._expires = None
        sections = self._sections()
        self._empty.setVisible(provider_id is None)
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
                            on_error=lambda e: (show_panel_error(self._only.body, e),
                                                show_panel_error(self._shared.body, e),
                                                show_panel_error(self._catalogue.body, e)))
        pid = provider_id
        self._run_query(lambda repos: repos.playback_events.summary(pid), self._on_playback,
                        token_ref=self._tokens["playback"],
                        on_error=lambda e: show_panel_error(self._playback.body, e))
        self._run_query(lambda repos: (repos.analytics.guide_coverage(pid),
                                       repos.providers.get_by_id(pid).account_exp_date),
                        self._on_catalogue, token_ref=self._tokens["catalogue"],
                        on_error=lambda e: show_panel_error(self._catalogue.body, e))
        self._run_query(lambda repos: repos.analytics.server_addresses(pid), self._on_addresses,
                        token_ref=self._tokens["addresses"],
                        on_error=lambda e: show_panel_error(self._addresses.body, e))
        self._run_query(lambda repos: repos.analytics.unrecognized_prefixes(pid), self._on_prefixes,
                        token_ref=self._tokens["prefixes"],
                        on_error=lambda e: show_panel_error(self._prefixes.body, e))

    def _sections(self) -> tuple[_Section, ...]:
        """In the order that answers "is this source worth keeping" first (Q2)."""
        return (self._only, self._shared, self._playback, self._addresses,
                self._catalogue, self._prefixes)

    def deactivate(self) -> None:
        """Drop every in-flight result (tab left, source switched, editor closed)."""
        for ref in self._tokens.values():
            ref[0] += 1

    def forget_cached_overlap(self) -> None:
        """The catalogue changed (a refresh finished): recompute on next open."""
        self._overlap = None

    # ── Sections ────────────────────────────────────────────────────────────

    def _on_overlap(self, overlap: TitleOverlapDTO) -> None:
        self._overlap = overlap
        self._render_overlap(overlap)

    def _render_overlap(self, overlap: TitleOverlapDTO) -> None:
        pid = self._provider_id
        me = next((s for s in overlap.sources if s.id == pid), None)
        if me is None:
            return
        others = [s for s in overlap.sources if s.id != pid]
        only = {m: overlap.only.get((pid, m), 0) for m, _ in MEDIA}
        totals = {m: overlap.totals.get((pid, m), 0) for m, _ in MEDIA}

        self._only.title.setText(f"Only on {me.name}")
        clear_layout(self._only.body)
        if not others:
            self._only.text(f"{_count_line(totals)} — this is your only source.")
        else:
            self._only.text(f"{_count_line(only)} — no other source has these.")
            ids = overlap.only_ids.get(pid, frozenset())
            if ids:
                browse = QPushButton("Browse them")
                browse.setToolTip(f"Show the {len(ids):,} channels only {me.name} carries in Search")
                _theme.style(browse, "LINK_BTN_SM")
                cursor_affordance.set_clickable(browse)
                browse.clicked.connect(lambda: self.browse_requested.emit(f"Only on {me.name}", ids))
                row = QHBoxLayout()
                row.addWidget(browse)
                row.addStretch(1)
                self._only.body.addLayout(row)

        clear_layout(self._shared.body)
        if not others:
            self._shared.text("No other sources to compare with.")
        else:
            grid = self._shared.grid()
            row = 0
            for other in others:
                muted = other.is_expired or not other.is_active
                name = source_state_label(other.name, other.is_active, other.is_expired)
                for media, _noun in MEDIA:
                    total = totals[media]
                    if not total:
                        continue
                    both = overlap.shared.get((pid, other.id, media), 0)
                    _bar_row(grid, row, f"{name} · {SHORT_NOUN[media]}", both / total,
                             f"{both / total:.0%}", f"{both:,} of {total:,}", muted=muted)
                    row += 1
            hint = redundancy_hint(overlap, pid)
            if hint:
                self._shared.text(hint)

        self._catalogue_counts = totals
        self._render_catalogue()

    def _on_catalogue(self, result: tuple[GuideCoverageDTO, datetime | None]) -> None:
        self._guide, self._expires = result
        self._render_catalogue()

    def _render_catalogue(self) -> None:
        """Needs both the overlap totals and the guide read; renders when both are in."""
        counts, guide = self._catalogue_counts, self._guide
        if counts is None or guide is None:
            return
        clear_layout(self._catalogue.body)
        parts = [_count_line(counts)]
        if guide.live_channels:
            pct = guide.with_guide / guide.live_channels
            line = f"guide data for {guide.with_guide:,} of {guide.live_channels:,} live channels ({pct:.1%})"
            if guide.guide_until:
                line += f", through {short_date_text(guide.guide_until)}"
            parts.append(line)
        self._catalogue.text(" · ".join(parts))
        if self._expires is None:
            self._catalogue.subtitle.setText("")
        else:
            days = (self._expires - datetime.now()).days
            self._catalogue.subtitle.setText("expired" if days < 0 else f"{days} days left")

    def _on_playback(self, summary: PlaybackSummaryDTO) -> None:
        clear_layout(self._playback.body)
        if not summary.attempts:
            self._playback.subtitle.setText("")
            self._playback.text("Nothing recorded yet — plays from this source are counted "
                                "from now on.")
            return
        self._playback.subtitle.setText(f"since {short_date_text(summary.since)}" if summary.since else "")
        ttp = summary.median_time_to_picture_ms
        facts = (
            ("Plays started", f"{summary.started:,} of {summary.attempts:,} "
                              f"({summary.started / summary.attempts:.0%})"),
            ("Never loaded", f"{summary.never_started:,}"),
            ("Refused — connections in use", f"{summary.refused:,}"),
            ("Dropped while playing", f"{summary.dropped:,}"),
            ("Time to picture", f"{ttp / 1000:.1f} s typical" if ttp else "not recorded yet"),
        )
        holder = QWidget()
        flow = FlowLayout(holder, h_spacing=24, v_spacing=6)
        flow.setContentsMargins(0, 0, 0, 0)
        for caption, value in facts:
            pair = QWidget()
            row = QHBoxLayout(pair)
            row.setContentsMargins(0, 0, 0, 0)
            name = QLabel(caption)
            _theme.style(name, "META_HINT")
            row.addWidget(name)
            figure = QLabel(value)
            _theme.style(figure, "FIELD_LABEL")
            row.addWidget(figure)
            flow.addWidget(pair)
        self._playback.body.addWidget(holder)

    def _on_addresses(self, addresses: list[ServerAddressDTO]) -> None:
        clear_layout(self._addresses.body)
        worked = sum(1 for a in addresses if a.worked)
        self._addresses.subtitle.setText(f"{worked} of {len(addresses)} have worked")
        if not addresses:
            self._addresses.text("No addresses.")
            return
        grid = self._addresses.grid()
        for row, a in enumerate(addresses[:ADDRESS_ROWS]):
            host = urlparse(a.url).netloc or a.url
            if not a.tried:
                _bar_row(grid, row, host, None, "—", "untested")
                continue
            speed = f"{a.median_latency_ms / 1000:.1f} s" if a.median_latency_ms else "—"
            _bar_row(grid, row, host, a.worked / a.tried, f"{a.worked / a.tried:.0%}", speed)
        rest = addresses[ADDRESS_ROWS:]
        if rest:
            self._addresses.text(f"+ {len(rest)} more, {sum(1 for a in rest if a.worked)} of them "
                                 "worked recently", "META_HINT")

    def _on_prefixes(self, prefixes: list[PrefixStatDTO]) -> None:
        clear_layout(self._prefixes.body)
        self._prefixes.subtitle.setText(f"{len(prefixes):,} the name parser does not know")
        if not prefixes:
            self._prefixes.text("Every prefix on this source is recognised.")
            return
        grid = self._prefixes.grid()
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)
        for row, stat in enumerate(prefixes[:PREFIX_ROWS]):
            code = QLabel(stat.prefix)
            _theme.style(code, "FIELD_LABEL")
            grid.addWidget(code, row, 0)
            count = QLabel(f"{stat.count:,}")
            _theme.style(count, "META_HINT")
            grid.addWidget(count, row, 1)
            sample = MiddleElideLabel(f"e.g. {stat.sample_names[0]}" if stat.sample_names else "",
                                      color_token="COLOR_MUTED_2")
            sample.setToolTip("\n".join(stat.sample_names))
            grid.addWidget(sample, row, 2)
        if len(prefixes) > PREFIX_ROWS:
            self._prefixes.text(f"+ {len(prefixes) - PREFIX_ROWS:,} more", "META_HINT")

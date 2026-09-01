"""Row widgets the Watch Alerts section renders.

Both are thin shells over :func:`metatv.gui.chip_row.build_chip_row`, the one
builder every other sidebar section already uses. They own only what a shared
builder cannot: the left slot's PAINTING (which marker applies right now), the
clock tick that rewrites their own time text, and — for :class:`_AlertRow` —
mouse handling, since it is the only sidebar row that is itself interactive.

Everything about their APPEARANCE now comes from the builder. That is the
point. Watch Alerts was the last section still hand-assembling a QHBoxLayout,
which is why its titles CLIPPED where every other list middle-elides, why its
chips were built from copied stylesheet strings that went stale on a theme
switch (``setStyleSheet`` renders once; ``theme.style_fn`` re-renders), and why
its spacing had to be re-derived by hand every time the design moved.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from metatv.core.epg_utils import is_local_today, now_utc, to_local
from metatv.gui import cursor_affordance
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.chip_row import (
    CHIP_LANG, CHIP_NEWS, CHIP_QUALITY, CHIP_YEAR, ROW_SPACING, build_chip_row,
    chip_widget, row_min_height,
)
from metatv.gui.progress_paint import ProgressBar, elapsed_pct
from metatv.gui.relative_time import humanize_remaining, humanize_until


#: The left slot's reserved width, and the marker size within it. 14px is the
#: sidebar's normal icon size — History's play-next button uses the same — not
#: the 11px a chip-row TYPE icon uses. That one is deliberately sized against a
#: title's cap height because it sits inline WITH text; this is a control in its
#: own column, and at 11px it read as half the size it should be.
SLOT_W = 18
SLOT_ICON_PX = 14

#: How far a child airing insets from its programme row — and, necessarily, how
#: wide the programme row's source-marker column is. ONE constant because the
#: two have to be equal: the marker is what pushes the parent's play slot into
#: the same column as its children's, so the play affordances form one
#: continuous line down the group. Two numbers that must match are one number.
_CHILD_INDENT = 14

#: Vertical padding per row, one side, INSIDE the mounted chip row.
#:
#: The history is worth keeping because both ends were wrong. 1px rendered
#: ~18px rows against the design's ~28px and read as cramped; 5px put 12px of
#: padding around a 17px line box, and the owner read the surplus as a whole
#: wasted row between every entry: "the space between each item is a wasted
#: row ... spacing between rows should be cut in half". Halved twice at the
#: owner's word — 12px, then 6px, then 3px.
#:
#: It is no longer the row's FLOOR. That was the bug: a floor only this file
#: applied left every other sidebar section summing its children instead, and
#: the sidebar rendered two row heights. The floor is
#: :func:`metatv.gui.chip_row.row_min_height`, shared by all of them.
ROW_PAD_Y = 1


#: How far a top-level row's TITLE sits from the row's left edge: the marker
#: column, the reserved play slot, and the gap between them. Anything that must
#: line up with the titles — the "Upcoming" heading — takes this rather than a
#: number that happens to match today.
TITLE_INDENT = _CHILD_INDENT + SLOT_W + ROW_SPACING


def _slot_label() -> QLabel:
    """The fixed left column every Watch Alerts row aligns against.

    Fixed width IS the feature. The play affordance used to be a button at the
    right edge shown on hover, so it shoved the progress bar sideways whenever
    the pointer crossed a row. A reserved column cannot reflow, whether it
    currently holds a marker or not — which is also what gives EPG, Movies and
    Series rows a single left edge.
    """
    slot = QLabel()
    slot.setFixedWidth(SLOT_W)
    slot.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return slot


class _RowShell(QWidget):
    """What a Watch Alerts row is, minus what it shows.

    Both rows are a ``build_chip_row`` widget mounted at zero inset, sized to
    the section's row height, and willing to be as narrow as the list makes
    them. That last part is the one that had to be stated: a row is laid out by
    ``setItemWidget``, and the list sizes it from the ITEM's size hint — so a
    row reporting its natural width (462px for a long rule name, against a
    300px sidebar) widens the list instead of eliding inside it. Reporting the
    minimum instead is what lets ``MiddleElideLabel`` do its job; it is why
    Watch Alerts titles clipped for as long as the section built its own rows.
    """

    def _mount(self, inner: QWidget) -> None:
        """Put the built row inside this one at zero inset.

        Zero margins matter beyond tidiness: ``_AlertRow`` maps child geometry
        into its own coordinates to hit-test the slot, and any inset here would
        put the two coordinate systems permanently out of step.
        """
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(inner)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # The floor is chip_row's now, not this file's. It started here
        # because Watch Alerts was the section that noticed clipped descenders,
        # but a floor only one section applies is a floor the sidebar does not
        # have — every other section stayed pinned at its children's 20px and
        # rendered shorter rows above a 13px app font. Reading it back keeps
        # the two in step by construction.
        self.setMinimumHeight(row_min_height())

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        """Full row height, minimum width.

        The height is the section's, not the inner chip row's tighter one; the
        width is the narrowest the row can be drawn at, so the hosting list
        never grows a horizontal scroll range and the title elides instead.
        """
        hint = super().sizeHint()
        return QSize(
            super().minimumSizeHint().width(),
            max(hint.height(), self.minimumHeight()),
        )


class _VodAlertRow(_RowShell):
    """A Movies / Series row: keyword rule or monitored series.

    Rendered by ``build_chip_row``; this class exists only to hold the slot and
    keep the widget mouse-transparent so the hosting ``QListWidget`` item keeps
    click / double-click / context-menu.
    """

    def __init__(self, text: str, count_text: str, parent=None, *,
                 suffix: str = "", is_new: bool = False, marker: str = ""):
        """
        Args:
            text: The title.
            count_text: The trailing count.
            parent: Qt parent.
            suffix: Collision disambiguator, shown dim after the title.
            is_new: Draws the green dot in the left slot, and makes the count a
                filled pill rather than an outlined chip — one decision in one
                place, instead of every call site computing its own sheet — the same column and the same markers the EPG rows
                use, so "new" reads identically wherever it appears.
            marker: An episode code ("S05E03") or year, chipped beside the
                title. A claim about THIS title, so it travels with it rather
                than sitting in the right rail.
        """
        super().__init__(parent)

        slot = _slot_label()
        if is_new:
            slot.setPixmap(_icon_utils.vector_pixmap(
                _icons.vector_key("new_dot"), _theme.COLOR_OK, SLOT_ICON_PX))
            slot.setToolTip("New since you last looked")

        self._mount(build_chip_row(
            title=text,
            title_suffix=suffix,
            title_chips=((CHIP_YEAR, marker),),
            chips=((CHIP_NEWS if is_new else CHIP_YEAR, count_text),),
            leading_slot=slot,
        ))
        # The item (not this widget) owns click/double-click/context-menu, so let
        # events pass through to the QListWidget viewport.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


class _AlertRow(_RowShell):
    """An EPG programme or one of its airings.

    The section's only interactive row: it emits its own signals and paints its
    own left slot. The visible row is a ``build_chip_row`` widget mounted
    inside it.
    """

    play_clicked = pyqtSignal()
    row_clicked  = pyqtSignal()  # single click anywhere except the play button
    #: An expandable row was clicked anywhere that is not its play button.
    #: Expansion used to be wired to ``play_clicked``, which meant the row had
    #: to count as PLAYABLE to expand at all — so its marker column drew a play
    #: triangle on hover and only that 18px strip responded. Owner: "clicking
    #: the show title ... does not expand the row", and "the carot turns into a
    #: play icon ... but it shouldn't because it is expanding or collapsing".
    expand_clicked = pyqtSignal()

    def __init__(self, ch_name: str, time_str: str, config, parent=None, *,
                 when: datetime | None = None, live: bool = False,
                 started_at: datetime | None = None, quality: str = "",
                 region: str = "",
                 indent: int = 0, bar_source: str = "",
                 expandable: bool = False, expanded: bool = False,
                 marker_column: bool | None = None):
        """
        Args:
            ch_name: The channel/title text for the row.
            time_str: The time text as of now — see :meth:`refresh_time`.
            config: The app config. Unused since the play glyph moved to the
                slot's vector icon; kept so call sites and tests are unchanged.
            parent: Qt parent.
            when: The programme's ``stop_time`` (live rows) or ``start_time``
                (upcoming rows), UTC-naive. Kept so the row can recompute its
                own text on a clock tick; ``None`` leaves the row frozen, which
                is right for rows whose text is not time-derived.
            live: True for a row counting DOWN to a programme's end, False for
                one counting up to its start. Picks the formatter.
            quality: A quality token ("RAW", "4K") chipped beside the title — a
                claim about THIS copy, so it travels with the title rather than
                sitting in the right rail.
            region: The source's region/language ("DE", "US"), chipped for the
                same reason. It used to be baked into the channel NAME as
                "[DE]", which left the programme row — the one whose play
                button starts a source without opening anything — unable to say
                what language you were about to get.
            indent: Left inset for a child row. The TREE used to supply this
                via setIndentation, which also indented top-level rows — so EPG
                titles started further right than Movies and Series ones and the
                section had two left edges.
            expandable: This row has children, so its slot shows a disclosure
                caret. Replaces the tree's native indicator, which lived in its
                own column and could not share the slot with play and new.
            expanded: Whether the source list is currently open.
            marker_column: Reserve the source-marker column. ``None`` means
                "whenever the row is expandable", which is the sensible default
                for a child row (no) and a bundled programme (yes). A
                SINGLE-source programme passes ``True`` explicitly: it has no
                sources to disclose but it is still a top-level row, and its
                title has to start where its neighbours' do.
            bar_source: The channel this row's progress bar belongs to, named
                in the bar's tooltip. A programme row's bar is not an abstract
                "the programme" — it is the progress of the ONE source its play
                button will start, so the tooltip says which.
            started_at: The programme's start, for a live row. With ``when``
                (its end) this gives the DURATION, which is what turns "13m
                left" into a proportion. Without it the row falls back to
                words — an upcoming row has no elapsed share to show.
        """
        super().__init__(parent)
        self._when = when
        self._live = live
        self._started_at = started_at
        self._playing = False
        self._is_new = False
        self._hovered = False
        self._expandable = expandable
        self._expanded = expanded
        marker_column = expandable if marker_column is None else marker_column

        # An expandable row carries TWO leading columns, and the widths are
        # what make them line up: the marker takes exactly _CHILD_INDENT, so
        # the play slot beside it starts at the same x as a CHILD row's slot.
        # The play affordances then form one continuous column down the group,
        # and the parent's title sits on the same left edge as its sources'.
        self._slot = _slot_label()
        self._marker = None
        if marker_column:
            # RESERVED, not conditional. A top-level EPG row keeps this column
            # whether or not it has sources to disclose, so a single-source
            # programme's title lands on the same left edge as a bundled one's.
            # Owner: "single item spacing needs to leave space for the play
            # button even if it's not there (so basically hold space for the
            # playlist icon, and the play button)". Reserving is the same
            # reasoning that gave the play slot its own fixed width — a column
            # that appears and disappears moves everything beside it.
            self._marker = QLabel()
            self._marker.setFixedWidth(_CHILD_INDENT)
            self._marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if expandable:
                self._marker.setToolTip("Several sources — click to show them")
            leading = QWidget()
            lay = QHBoxLayout(leading)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            lay.addWidget(self._marker)
            lay.addWidget(self._slot)
        else:
            leading = self._slot

        # A live row with a known duration shows the bar; everything else keeps
        # the words. An upcoming row has no elapsed share, and a live row whose
        # provider gave no start_time has no denominator.
        #
        # A programme row gets one too. It used to chip its time instead, on the
        # reasoning that its airings carried the bars and a parent/child pair
        # would measure the same thing twice — but that only holds while the row
        # is OPEN, and closed is the default. Collapsed, the programme row is
        # the only thing on screen, so it is the row that most needs the
        # proportion the bar exists to show. Owner: "the bundled results ...
        # should use progress bars corresponding to the source attached to the
        # play button." Which is exactly what it now shows: the parent is built
        # from the same airing its play button starts.
        self._show_bar = bool(
            live and when is not None and started_at is not None
        )
        self._bar_source = bar_source

        # Built at its REAL fill, not at zero. It used to start empty and only
        # correct on the first 30s tick, so every bar rendered as a sliver for
        # up to half a minute and then jumped — which reads as the app being
        # wrong rather than as the programme progressing.
        self.progress = None
        if self._show_bar:
            self.progress = ProgressBar(
                elapsed_pct(started_at, when, now_utc()), width=44, height=8)
            self.progress.setToolTip(self._bar_tip(time_str))

        # A row shows EITHER a bar or its time, never both: the bar already
        # encodes the remaining time as a proportion and carries the words in
        # its tooltip. The time is a chip because every other trailing fact in
        # this section is one, and a naked string beside them reads as a
        # different KIND of thing.
        #
        # Built here rather than declared as `chips=` so the row keeps a direct
        # reference for `refresh_time`. Fishing it back out of the assembled row
        # by matching text would return the wrong widget the moment a title
        # equalled a time string.
        self.time_lbl = None if self._show_bar else chip_widget(CHIP_YEAR, time_str)

        self._mount(build_chip_row(
            title=ch_name,
            title_chips=((CHIP_QUALITY, quality),),
            # Language in the RIGHT rail, not with the title: hugging the title
            # put every row's chip at a different x, since it lands wherever the
            # name happens to end. Owner: "the alignment of the language chips
            # should be align right immediately to the left of the progress bar
            # or upcoming play time chip." Quality stays with the title — that
            # was settled separately and for the opposite reason.
            chips=((CHIP_LANG, region),),
            tail_widget=self.progress if self._show_bar else self.time_lbl,
            leading_slot=leading,
            indent=indent,
        ))
        self.setMouseTracking(True)
        cursor_affordance.set_clickable(self)
        self._paint_slot()

    def _bar_tip(self, time_text: str) -> str:
        """The bar's hover text, naming the source it measures.

        A programme row's bar is one channel's progress — the channel its play
        button starts — so saying which is what stops the bar reading as a
        claim about the programme in the abstract.
        """
        return f"{time_text} · {self._bar_source}" if self._bar_source else time_text

    # ── the left slot ────────────────────────────────────────────────────
    def set_playing(self, playing: bool) -> None:
        """Mark this row as the thing currently playing."""
        if playing != self._playing:
            self._playing = playing
            self._paint_slot()

    def set_expanded(self, expanded: bool) -> None:
        """Point the disclosure caret the other way."""
        if expanded != self._expanded:
            self._expanded = expanded
            self._paint_slot()

    def set_new(self, is_new: bool) -> None:
        """Mark this row as new since the viewer last looked."""
        if is_new != self._is_new:
            self._is_new = is_new
            self._paint_slot()

    def _offers_play(self) -> bool:
        """Whether this row can be played at all.

        Only a LIVE row can. Offering ▶ on an upcoming programme promises
        something the app cannot do — owner: "how can it play anything in
        future... no time machine." An upcoming row's useful action is opening
        it, which the row click already does.
        """
        return self._live

    def _paint_slot(self) -> None:
        """Draw whichever marker applies, most urgent first.

        Playing beats hover beats new: what is on screen right now outranks an
        offer to start it, which outranks a note that this arrived recently.
        Only one shows, which is what lets them share one column.

        Green carries both "playing" and "new", but as different SHAPES — a
        triangle and a dot — so neither state rests on colour alone. Green for
        playing is the convention the details pane already uses
        (``DETAIL_PLAY_BTN_PLAYING``); the similarly-named
        ``COLOR_PLAYBACK_IN_PROGRESS`` is ORANGE and means *resumable*, which is
        a different claim entirely.
        """
        # The marker is a column of its own, so it no longer competes with the
        # play affordance for the one slot — which is what made an expandable
        # row draw a play triangle where its disclosure control should be.
        if self._marker is not None and self._expandable:
            self._marker.setPixmap(_icon_utils.vector_pixmap(
                _icons.vector_key(
                    "sources_open" if self._expanded else "sources_closed"),
                _theme.COLOR_OK if self._is_new else _theme.COLOR_TEXT,
                SLOT_ICON_PX - 2,
            ))
            self._marker.setToolTip(
                "Hide the other sources" if self._expanded
                else "Several sources — click to show them"
            )

        if self._playing:
            self._set_slot_icon("play", _theme.COLOR_OK, "Playing now")
        elif self._hovered and self._offers_play():
            self._set_slot_icon("play", _theme.COLOR_ACCENT,
                                "Play the first available source"
                                if self._expandable else "Play")
        elif self._is_new:
            self._set_slot_icon("new_dot", _theme.COLOR_OK, "New since you last looked")
        else:
            self._slot.clear()
            self._slot.setToolTip("")

    def _set_slot_icon(self, key: str, colour: str, tip: str) -> None:
        self._slot.setPixmap(
            _icon_utils.vector_pixmap(_icons.vector_key(key), colour, SLOT_ICON_PX)
        )
        self._slot.setToolTip(tip)

    def refresh_time(self, now: datetime) -> None:
        """Recompute this row's time text against ``now``.

        Called from the section's 30-second tick. The text is a pure function of
        ``now`` and a timestamp already held here, so this costs no query and no
        network — which is the whole reason the row keeps ``when`` instead of
        only the rendered string it was built with.

        A no-op when the text has not changed, so a tick over a full sidebar
        does not dirty every row and force a repaint of rows that still read
        correctly.

        Args:
            now: The current instant, UTC-naive (``epg_utils.now_utc()``).
        """
        if self._when is None:
            return
        text = (
            humanize_remaining(self._when, now) if self._live
            else humanize_until(self._when, now,
                                to_local=to_local, is_local_today=is_local_today)
        )
        if self.time_lbl is not None and text != self.time_lbl.text():
            self.time_lbl.setText(text)
        if self.progress is not None:
            # The bar advances on the same tick, from the same instant, so the
            # fill and the tooltip can never disagree about the time.
            self.progress.set_pct(
                elapsed_pct(self._started_at, self._when, now),
                tooltip=self._bar_tip(text),
            )

    def _slot_rect(self) -> QRect:
        """The slot's geometry in THIS widget's coordinates.

        The slot lives inside the built row now, so its own ``geometry()`` is
        relative to that child and not to the row the click arrived on.
        """
        top_left = self._slot.mapTo(self, QPoint(0, 0))
        return QRect(top_left, self._slot.size())

    def mousePressEvent(self, event):
        # The slot IS the play control while it is offering to play — clicking
        # the triangle starts it. Everything else on the row goes to the row's
        # own action, which for an expandable row is to open it: the title, the
        # time, the marker and the empty space all expand, so the gesture is
        # the whole row rather than one 18px strip of it.
        if self._slot_rect().contains(event.pos()) and (
            self._playing or (self._hovered and self._offers_play())
        ):
            self.play_clicked.emit()
        elif self._expandable:
            self.expand_clicked.emit()
        else:
            self.row_clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self._paint_slot()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._paint_slot()
        super().leaveEvent(event)

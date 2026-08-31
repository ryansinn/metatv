"""Events view — one view over the dated content, with a scope switch.

``special_view`` carries three values and two of them are *events*: ``ppv``
(510 rows on the owner's library) and ``live_event`` (2,319). The third,
``sports``, is 28,018 CHANNELS and has its own view — a sports channel is a
place you go, an event is a thing that happens at a time, and the difference is
what the countdown on every card is for.

One view with a scope switch rather than two views, settled against the
rendered mockup: the rows are the same shape and the difference is a stored
enum. ``get_events_channels(scope, bucket)`` is already parameterised for it.

Supersedes ``ppv_view.py``, which was 230 orphaned lines that queried on the UI
thread, held ORM objects in its cards and read them after the session closed,
and excluded no hidden provider. The card's countdown was the good part and it
is what survives — on a DTO, and with the ladder moved into
``relative_time.humanize_countdown`` where the other two forward formatters
live.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from loguru import logger
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.content_view import ContentView
from metatv.gui.cursor_affordance import set_clickable
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.relative_time import humanize_countdown, is_countdown_live
from metatv.gui.view_scope import resolve_visibility_scope

#: (bucket, label, tooltip). ``""`` means both buckets — the default, because
#: the question "what is on" does not start by caring which kind it is.
SCOPES: tuple[tuple[str, str, str], ...] = (
    ("", "All", "Every dated event"),
    ("ppv", "Pay-per-view", "Events the provider bills separately"),
    ("live_event", "Live events", "Scheduled programmes on an event feed"),
)

#: Repaint cadence for the countdowns. Only cards under a day away are ticked —
#: see is_countdown_live.
_TICK_MS = 1000


class _EventCard(QFrame):
    """One dated event.

    Holds a DTO, never an ORM row: the card outlives the session that produced
    it by minutes, and a detached ``ChannelDB`` raises ``DetachedInstanceError``
    on the next attribute read. ``ppv_view.py`` stored the ORM object and read
    ``channel.event_start_time`` on every timer tick.
    """

    play_requested = pyqtSignal(str)      # channel_id
    select_requested = pyqtSignal(str)    # channel_id

    _CARD_W = 300

    def __init__(self, dto, parent=None) -> None:
        """
        Args:
            dto: A ``SpecialContentDTO``.
            parent: Qt parent.
        """
        super().__init__(parent)
        self.dto = dto
        self._meta: dict = dto.event_metadata or {}
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
        self.setFixedWidth(self._CARD_W)
        _theme.style(self, "EVENT_CARD")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        # The event's own name when the classifier parsed one out of the
        # provider's pipe-delimited string; the channel name is the fallback,
        # not the preference — it reads "End | India tour of Sri Lanka 2026 -
        # 2nd Test | all | 27-08-2026 | 00:00 (GMT) | 8K EXCLUSIVE".
        title = self._meta.get("event_name") or self.dto.detected_title or self.dto.name
        self.title_label = QLabel(title, self)
        self.title_label.setWordWrap(True)
        _theme.style(self.title_label, "EVENT_CARD_TITLE")
        # Exactly TWO lines, always. A wrapped QLabel in a QVBoxLayout reports a
        # one-line sizeHint, so a three-line title was drawn into a box sized for
        # less and clipped through the middle of the glyphs. Pinning the height
        # to a whole number of lines means an over-long title is cut at a LINE
        # boundary instead, and every card in the grid is the same height.
        #
        # Two rather than one because these are fixture names — "X v Y <League>
        # <Matchweek>" — where one line loses the teams. The full text is the
        # tooltip either way.
        # ensurePolished() first: a stylesheet font is resolved at POLISH time,
        # so fontMetrics() straight after _theme.style() still reports the
        # inherited font and pins the box to the wrong number of pixels — 34
        # where the styled font needs 40, which reintroduces the clipping this
        # is fixing.
        self.title_label.ensurePolished()
        _fm = self.title_label.fontMetrics()
        self.title_label.setFixedHeight(_fm.lineSpacing() * 2)
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.title_label.setToolTip(title)
        layout.addWidget(self.title_label)

        self.when_label = QLabel("", self)
        # EVENTS_TIME_HINT already means "the time/availability hint on an
        # event row" — the EPG events list has used it since before this
        # view existed.
        _theme.style(self.when_label, "EVENTS_TIME_HINT")
        layout.addWidget(self.when_label)

        self.countdown_label = QLabel("", self)
        _theme.style(self.countdown_label, "EVENT_CARD_COUNTDOWN")
        layout.addWidget(self.countdown_label)

        badges = QHBoxLayout()
        badges.setSpacing(6)
        for text in self._badge_texts():
            chip = QLabel(text, self)
            _theme.style(chip, "EVENT_CARD_BADGE")
            badges.addWidget(chip)
        badges.addStretch()
        layout.addLayout(badges)

        self.play_button = QPushButton(f"{_icons.play_icon} Play", self)
        self.play_button.setToolTip(f"Play {self.dto.name}")
        # style_fn, not a role: COLOR_PPV_ACCENT is a saturated FILL, so the
        # label colour has to come from on_fill() — which is defined after the
        # semantic-constant builder runs and cannot be called from it. Hover
        # moves the border and keeps the on-fill foreground, the correction
        # DETAIL_RESUME_BTN needed when switching to the on-background ramp made
        # its label vanish against its own fill.
        _theme.style_fn(self.play_button, lambda: (
            "QPushButton { background: " + _theme.COLOR_PPV_ACCENT + ";"
            " color: " + _theme.on_fill(_theme.COLOR_PPV_ACCENT) + ";"
            " border: 1px solid " + _theme.COLOR_PPV_ACCENT + ";"
            " border-radius: " + _theme.RADIUS_SM + "; padding: 6px 12px;"
            " font-weight: bold; font-size: " + _theme.FONT_MD + "; }"
            "QPushButton:hover { background: " + _theme.COLOR_PPV_ACCENT + ";"
            " color: " + _theme.on_fill(_theme.COLOR_PPV_ACCENT) + ";"
            " border-color: " + _theme.COLOR_TEXT_HI + "; }"
        ))
        set_clickable(self.play_button)
        self.play_button.clicked.connect(
            lambda: self.play_requested.emit(self.dto.id))
        layout.addWidget(self.play_button)

        self.setToolTip(self.dto.name)

    def _badge_texts(self) -> list[str]:
        """Whatever this bucket happens to carry.

        The two buckets have different keys — that is the providers' doing, not
        ours — so this reads what is there rather than assuming a shape. ppv
        rows carry quality and sport_type; live_event rows carry network and
        region.
        """
        out = []
        # ``str.title`` alone renders the classifier's canonical "mma" as
        # "Mma". Short values in this vocabulary are acronyms (mma, ufc, f1),
        # longer ones are words (soccer, hockey) — so the length is the rule.
        def _sport(v: str) -> str:
            return v.upper() if len(v) <= 3 else v.title()

        for key, transform in (("quality", str.upper),
                               ("sport_type", _sport),
                               ("network", str),
                               ("region", str.upper)):
            value = self._meta.get(key)
            if value:
                out.append(transform(str(value)))
        if self.dto.detected_quality and "quality" not in self._meta:
            out.append(self.dto.detected_quality.upper())
        return out[:3]

    def refresh_countdown(self, now: datetime) -> None:
        """Re-render the time strings against *now*.

        Args:
            now: The tick's instant, supplied by the view — never read from the
                clock in here, so the whole grid renders one consistent frame.
        """
        start = self.dto.event_start_time
        if start is None:
            # 923 of the owner's live_event rows have availability "always" and
            # no start at all. "Date unavailable" would be a lie about a feed
            # that is simply always on.
            self.when_label.setText("Always available")
            self.countdown_label.setText("")
            return
        self.when_label.setText(start.strftime("%a %b %-d, %-I:%M %p"))
        self.countdown_label.setText(humanize_countdown(start, now))

    def wants_ticks(self, now: datetime) -> bool:
        """Whether this card's countdown changes within the second."""
        return is_countdown_live(self.dto.event_start_time, now)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        """A click anywhere on the card selects it; the button plays it."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.select_requested.emit(self.dto.id)
        super().mouseReleaseEvent(event)


class EventsView(ContentView):
    """Dated content — pay-per-view and live events — with a scope switch."""

    channelSelected             = pyqtSignal(str)
    playRequested               = pyqtSignal(str)
    channelMiddleClicked        = pyqtSignal(str)
    channelContextMenuRequested = pyqtSignal(str, int, int)

    def __init__(self, db, config, run_query: Callable, parent=None) -> None:
        """
        Args:
            db: Database instance; every read goes through *run_query*.
            config: Live ``Config`` — the control layer resolves exclusions off
                it before the worker sees a scope (DR-0007).
            run_query: ``MainWindow._run_query``, the single async-read seam.
            parent: Qt parent.
        """
        super().__init__(config, parent)
        self._db = db
        self._run_query = run_query
        self._bucket = ""
        self._cards: list[_EventCard] = []
        self._token: list[int] = [0]

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

        self._setup_ui()

    # ------------------------------------------------------------------ #
    # Construction                                                        #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.scope_buttons: dict[str, QPushButton] = {}
        for bucket, label, tip in SCOPES:
            btn = QPushButton(label, self)
            btn.setCheckable(True)
            btn.setChecked(bucket == self._bucket)
            btn.setToolTip(tip)
            set_clickable(btn)
            btn.clicked.connect(lambda _=False, b=bucket: self._set_bucket(b))
            self.scope_buttons[bucket] = btn
            bar.addWidget(btn)
        self._style_scope_buttons()
        bar.addStretch()
        self.count_label = QLabel("", self)
        _theme.style(self.count_label, "ITEM_COUNT")
        bar.addWidget(self.count_label)
        layout.addLayout(bar)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_container = QWidget()
        self.grid = FlowLayout(self.grid_container, spacing=14)
        self.scroll.setWidget(self.grid_container)
        layout.addWidget(self.scroll, 1)

        self.message_label = QLabel("", self)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _theme.style(self.message_label, "EVENT_EMPTY_MSG")
        self.message_label.hide()
        layout.addWidget(self.message_label)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def on_activate(self) -> None:
        self._reload()
        self._timer.start()

    def on_deactivate(self) -> None:
        """Stop ticking and drop any in-flight result.

        Both halves matter: a 1 Hz timer behind a hidden view is pure waste, and
        a result that lands after the switch would paint over whatever the user
        moved to.
        """
        self._timer.stop()
        self._token[0] += 1

    def get_view_name(self) -> str:
        return "events"

    # ------------------------------------------------------------------ #
    # Loading                                                             #
    # ------------------------------------------------------------------ #

    def _style_scope_buttons(self) -> None:
        """Swap the segment role on each button.

        ``EVENTS_SEG_ACTIVE`` / ``EVENTS_SEG_INACTIVE`` already exist and mean
        exactly this — "Events tab, segmented view-mode toggle" — and the EPG
        events list applies them by swapping, not by a ``:checked`` rule. A
        third role with the same property set is what
        ``test_theme_role_duplication`` exists to stop.
        """
        for value, btn in self.scope_buttons.items():
            _theme.style(btn, "EVENTS_SEG_ACTIVE" if value == self._bucket
                         else "EVENTS_SEG_INACTIVE")

    def _set_bucket(self, bucket: str) -> None:
        was = self._bucket
        self._bucket = bucket
        for value, btn in self.scope_buttons.items():
            btn.setChecked(value == bucket)
        self._style_scope_buttons()
        self._bucket = was
        if bucket != was:
            self._bucket = bucket
            self._reload()

    def _reload(self) -> None:
        config = self.config
        bucket = self._bucket

        def query(repos) -> list:
            scope = resolve_visibility_scope(repos, config)
            if bucket:
                return repos.channels.get_events_channels(scope, bucket)
            # "All" is both buckets, not a third query shape.
            rows = []
            for value, _label, _tip in SCOPES:
                if value:
                    rows.extend(repos.channels.get_events_channels(scope, value))
            return rows

        self._run_query(
            query, self._on_loaded, token_ref=self._token,
            on_error=lambda exc: self._show_message(
                f"{_icons.notification_warning_icon} Couldn't load these events"),
        )

    def _on_loaded(self, rows: Any) -> None:
        if rows is None:
            self._show_message(
                f"{_icons.notification_warning_icon} Couldn't load these events")
            return
        now = datetime.now()
        self._clear()
        for dto in self._ordered(rows, now):
            card = _EventCard(dto, self.grid_container)
            card.play_requested.connect(self.playRequested)
            card.select_requested.connect(self.channelSelected)
            card.refresh_countdown(now)
            self._cards.append(card)
            self.grid.addWidget(card)
        self.count_label.setText(self._count_line(rows, now))
        if not rows:
            self._show_message("No events in this scope")
        else:
            self.message_label.hide()

    @staticmethod
    def _count_line(rows, now: datetime) -> str:
        """The count, and how much of it is still ahead of you.

        Worth saying because it is often none: every one of the owner's 408 ppv
        rows has a start time in the PAST — the provider's listings went stale
        and nothing in the app could show that before this view existed. A bare
        "408 events" over a screen of finished fights reads as a bug in the
        view rather than a fact about the catalogue.

        Args:
            rows: The DTOs about to be rendered.
            now: The instant to compare against.

        Returns:
            ``"408 events · none upcoming"`` / ``"301 events · 12 upcoming"``.
        """
        if not rows:
            return ""
        upcoming = sum(1 for d in rows
                       if d.event_start_time is not None
                       and d.event_start_time >= now)
        noun = "event" if len(rows) == 1 else "events"
        tail = f"{upcoming:,} upcoming" if upcoming else "none upcoming"
        return f"{len(rows):,} {noun} · {tail}"

    @staticmethod
    def _ordered(rows, now: datetime) -> list:
        """Soonest first, then what has ended, then what has no date.

        Three groups rather than one sort key: an event with no start is not
        "infinitely far away", it is a feed that is always on, and burying it
        under 900 finished fights would be the wrong answer to "what can I
        watch". Sorting is stable within each group.
        """
        upcoming, past, undated = [], [], []
        for dto in rows:
            start = dto.event_start_time
            if start is None:
                undated.append(dto)
            elif start >= now:
                upcoming.append(dto)
            else:
                past.append(dto)
        upcoming.sort(key=lambda d: d.event_start_time)
        past.sort(key=lambda d: d.event_start_time, reverse=True)
        return upcoming + past + undated

    # ------------------------------------------------------------------ #
    # Ticking                                                             #
    # ------------------------------------------------------------------ #

    def _tick(self) -> None:
        """Repaint only the cards whose countdown actually moves.

        One shared timer for the whole grid, and one ``now`` for the frame — so
        every card in a screenful reads the same instant, which a per-card
        ``datetime.now()`` cannot promise. Cards more than a day out say
        "in 3d 4h" and that is stable for the next hour; ticking 2,800 of them
        at 1 Hz would burn the UI thread to change nothing.
        """
        now = datetime.now()
        for card in self._cards:
            if card.wants_ticks(now):
                card.refresh_countdown(now)

    # ------------------------------------------------------------------ #
    # State                                                               #
    # ------------------------------------------------------------------ #

    def _clear(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item is not None and item.widget():
                item.widget().deleteLater()
        self._cards.clear()

    def _show_message(self, text: str) -> None:
        """Render a visible message instead of an empty grid.

        CLAUDE.md's async-read rule: a failed load must never look like a
        silently-empty result. The same slot carries "no events in this scope",
        which is a different fact and says so.
        """
        logger.info("EventsView: {}", text)
        self._clear()
        self.count_label.setText("")
        self.message_label.setText(text)
        self.message_label.show()

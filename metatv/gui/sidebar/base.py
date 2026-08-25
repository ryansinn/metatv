"""CollapsibleSection base class and shared helpers for sidebar sections."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidgetItem, QPushButton,
    QFrame, QSizePolicy, QTreeWidgetItem,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from loguru import logger

from metatv.core.channel_name_utils import parse_channel_name
from metatv.gui import cursor_affordance
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

# Minimum height when a section is expanded: header (~26px) + room for ≥2 rows.
# The splitter enforces this so the user cannot drag an expanded section below it.
_MIN_EXPANDED = 80   # absolute floor; a section's own MIN_ROWS usually raises it

# Row fitting lives in row_budget.py — see there for why "+N more" is an
# allocation consequence and not a cap. The sentinel is re-exported because
# callers already reach for it here.
from metatv.gui.sidebar.row_budget import (  # noqa: F401
    _MORE_ROLE,
    _MORE_ROW,
    RowBudgetMixin,
)


def _floor_of(widget) -> int:
    """The expanded floor for *widget*, falling back for non-section children."""
    fn = getattr(widget, "min_expanded_height", None)
    return fn() if callable(fn) else _MIN_EXPANDED


class _ClickableHeader(QWidget):
    """A QWidget header that emits ``clicked`` on any mouse-press not consumed by a child.

    Child ``QPushButton`` widgets (action buttons, toggle arrow) intercept their own
    clicks via Qt's normal event propagation — they never reach this widget's
    ``mousePressEvent``.  Clicks on the title label or empty header padding do reach it
    and fire ``clicked``, allowing the full header area to act as a collapse/expand toggle.
    """

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        cursor_affordance.set_clickable(self)
        # Tint the header container ONLY: an unscoped background-color cascades onto
        # the title label + link buttons, stacking the overlay into a darker box.
        # The objectName lets SECTION_HEADER_TINT's ``#sectionHeader`` selector pin
        # the tint to this widget.
        self.setObjectName("sectionHeader")
        _theme.style(self, "SECTION_HEADER_TINT")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self.clicked.emit()
        super().mousePressEvent(event)


def _fmt_channel_name(
    name: str,
    fallback_year: str = "",
    *,
    detected_title: str | None = None,
    detected_year: str | None = None,
    detected_region: str | None = None,
    detected_quality: str | None = None,
) -> str:
    """Format a channel name for text-only lists: 'title · year [REGION] [QUALITY]'.

    Title first, year as immediate qualifier, tags at the right margin.
    ``fallback_year`` is used when no year is available (e.g. from MetadataDB).

    When the caller supplies ingestion-computed ``detected_*`` fields (the sidebar
    DTO callers), they are used verbatim — render code must NOT re-parse the name
    (compute-at-ingestion rule).  Re-parsing at render disagrees with the stored
    value whenever ``detected_region`` was filled from the provider category or a
    sibling channel rather than the name, so the sidebar would drop a [REGION] tag
    every other view shows.  Callers with only a raw string (e.g. a live EPG
    programme title in Alerts) omit the fields and fall back to parse_channel_name.
    """
    if detected_title is not None:
        # Stored mode — read the ingestion-computed fields, never parse at render.
        parts = [detected_title or name]
        year = detected_year or fallback_year
        if year:
            parts.append(f"· {year}")
        tags = []
        if detected_region:
            tags.append(f"[{detected_region}]")
        if detected_quality:
            tags.append(f"[{detected_quality}]")
        if tags:
            parts.append(" ".join(tags))
        return " ".join(parts)

    # Fallback for a raw name with no stored fields (e.g. a live EPG title).
    p = parse_channel_name(name)
    parts = [p.bare_name or name]

    year = p.year or fallback_year
    if year:
        parts.append(f"· {year}")

    tags = []
    if p.region:
        tags.append(f"[{p.region}]")
    if p.audio:
        tags.append(f"[{p.audio}]")
    if p.lang:
        tags.append(f"[{p.lang}]")
    if p.quality:
        tags.append(f"[{p.quality[0]}]")
    if tags:
        parts.append(" ".join(tags))

    return " ".join(parts)


class ScrollPreservingMixin:
    """Keeps a list's scroll position across the clear-and-repopulate cycle.

    Clearing a ``QListWidget`` resets its scroll to 0, so a section that
    rebuilds its list as the side effect of one action throws the user back to
    row 1 — punishing them for acting on any row but the first, in exactly the
    long lists that exist for bulk triage (owner report, repeatedly).

    #275 solved this inside ``BackgroundRefreshMixin``. It lives here instead
    because that mixin is not universal: ``RecommendedSection`` deliberately
    does not compose it (its ``None`` means a valid empty state, not a load
    failure), and so kept resetting to the top on every refresh — including the
    one its own "show versions separately" action triggers. One definition,
    inherited by every section through ``CollapsibleSection``, rather than a
    second copy for the exception.

    Usage is always the same three beats: ``_capture_scroll(lst)`` BEFORE the
    clear, ``_restore_scroll(lst)`` after the new rows are in, and
    ``_drop_captured_scroll()`` on any branch that renders a short placeholder
    instead of the rows.
    """

    @staticmethod
    def _scroll_offset(list_widget) -> int:
        """Current vertical scroll offset, or 0 when the widget has no bar yet."""
        bar = (
            list_widget.verticalScrollBar()
            if hasattr(list_widget, "verticalScrollBar") else None
        )
        return bar.value() if bar is not None else 0

    def _capture_scroll(self, list_widget) -> None:
        """Stash the current offset ahead of the clear that destroys it."""
        self._pending_scroll = self._scroll_offset(list_widget)

    def _drop_captured_scroll(self) -> None:
        """Forget a stashed offset.

        For renders that replace the rows with a short placeholder (a load
        error, "rate more content"): restoring a deep offset there would scroll
        the message itself out of view.
        """
        self.__dict__.pop("_pending_scroll", None)

    def _restore_scroll(self, list_widget) -> None:
        """Put the list back where the user had it, clamped to the new content.

        Clamping matters: the refresh may have returned FEWER rows (the item was
        removed from the queue), so the old offset can exceed the new maximum.
        Qt clamps on assignment, but doing it explicitly keeps the intent
        obvious and the value inspectable in tests.
        """
        offset = self.__dict__.pop("_pending_scroll", 0)
        if not offset:
            return
        bar = (
            list_widget.verticalScrollBar()
            if hasattr(list_widget, "verticalScrollBar") else None
        )
        if bar is None:
            return
        bar.setValue(min(offset, bar.maximum()))


class InPlaceRowMixin:
    """Take ONE row out of a rendered list instead of rebuilding the section.

    Owner: "the entire watch queue still refreshes when a single line is
    removed." Every sidebar mutation funnelled into ``section.refresh()``, which
    re-reads the whole table off-thread and rebuilds every row's widget — on a
    612-entry queue that is 600 chip rows destroyed and rebuilt to delete one.
    Preserving the scroll position (#290) hid the jump, not the work.

    So single-row removals now take the row out directly. This is a strict
    subset of refresh's job and deliberately narrow: it removes rows the caller
    has ALREADY deleted from the DB, and returns False when it cannot find them,
    so the caller can fall back to a full refresh rather than leave the sidebar
    disagreeing with the database. Anything that changes ordering, grouping or
    membership beyond the removed row still refreshes.

    A section opts in by implementing :meth:`_removal_list` (usually its
    ``_refresh_list``) and, when its rows do not key on a plain ``UserRole``
    string, :meth:`_row_matches`.
    """

    def _removal_list(self):
        """The QListWidget rows are removed from. Defaults to the refresh list."""
        return self._refresh_list()

    def _row_matches(self, item, key) -> bool:
        """True when *item* is the row identified by *key* (default: UserRole)."""
        return item.data(Qt.ItemDataRole.UserRole) == key

    def _after_rows_removed(self, list_widget) -> None:
        """Hook for post-removal bookkeeping (headers, counts, empty state)."""
        return None

    def remove_row(self, key) -> bool:
        """Remove the row(s) matching *key*. True if anything was removed.

        False means "not rendered here" — the caller must then do a full
        refresh, because a silent no-op would leave a deleted item on screen.
        """
        lst = self._removal_list()
        removed = False
        for index in reversed(range(lst.count())):
            item = lst.item(index)
            if not self._row_matches(item, key):
                continue
            # setItemWidget'd widgets are not owned by the item — drop the widget
            # explicitly or every removal leaks one (the suite's Qt leak guard
            # would report them, and 600 leaked chip rows is real memory).
            widget = lst.itemWidget(item)
            if widget is not None:
                lst.removeItemWidget(item)
                widget.deleteLater()
            lst.takeItem(index)
            removed = True
        if removed:
            self._after_rows_removed(lst)
        return removed

    @staticmethod
    def _prune_empty_headers(list_widget) -> None:
        """Drop any group header with no rows left under it.

        Headers are the non-selectable (``NoItemFlags``) rows every section
        renders above a group; one left standing over nothing misdescribes the
        list. Walks backwards so indices stay valid as items are taken.
        """
        count = list_widget.count()
        for index in reversed(range(count)):
            item = list_widget.item(index)
            if item.flags() != Qt.ItemFlag.NoItemFlags:
                continue
            following = list_widget.item(index + 1) if index + 1 < list_widget.count() else None
            if following is None or following.flags() == Qt.ItemFlag.NoItemFlags:
                list_widget.takeItem(index)


class CollapsibleSection(RowBudgetMixin, ScrollPreservingMixin, InPlaceRowMixin, QFrame):
    """Base class for collapsible sidebar sections with resize support"""

    # Signal when section wants to update its size
    sizeChanged = pyqtSignal()
    # "Explore →" header link clicked — the host opens this section's Explore view
    # (cascading columns seeded with the section's contents).  Only sections that
    # set EXPLORE_KEY grow the link, so only they emit it.
    exploreClicked = pyqtSignal()

    # EXPLORE_SOURCES key whose Explore view this section's header link opens.
    # None (the default) → no "Explore →" link on this section.
    EXPLORE_KEY: str | None = None

    # How many content rows this section needs before it stops being worth
    # showing at all.  A single global floor let a section be squeezed to ~2
    # rows: the owner's saved layout had History at 91px against Watch Queue's
    # 403px, which is not a preference, it is the arithmetic falling out of
    # whatever order the panes happened to be resized in.  Sections override
    # this when their rows carry more (Alerts nests three sub-groups) or less.
    MIN_ROWS: int = 3
    ROW_H: int = 24        # one content row, incl. its sub-line
    HEADER_H: int = 26

    #: Extra rows a section is allowed while it has NEWS. Bounded on purpose —
    #: "a section widens when it has something to say" must not become "the
    #: section with news takes the sidebar". It relaxes on its own the moment
    #: :meth:`news` goes quiet again (R13, mechanism 3).
    NEWS_BOOST_ROWS: int = 2

    #: Whether :meth:`news` last reported something. Plain state rather than a
    #: call inside :meth:`min_expanded_height`, because that method is invoked
    #: with the CLASS as ``self`` in several places ("this type's floor, no
    #: instance needed") — and a class cannot answer a question about its
    #: current contents. Updated wherever the header status is built.
    _news_active: bool = False

    def __init__(self, title: str, icon: str, config, parent=None,
                 vector_role: str | None = None):
        super().__init__(parent)
        self.title = title
        self.icon = icon
        # Semantic key into icons.VECTOR_KEYS. When set, the header draws a
        # monochrome vector glyph that follows the palette instead of *icon*,
        # which is an emoji and therefore fixed-colour and platform-dependent.
        # Left None the section keeps its emoji, so this converts section by
        # section rather than in one flag day.
        self.vector_role = vector_role
        self.config = config
        self.is_collapsed = False
        self.is_empty = True
        self._user_collapsed = False  # True when user (or restore) explicitly collapsed
        self._expanded_height: int = _MIN_EXPANDED  # remembered across collapse/expand cycles

        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(self.min_expanded_height())  # splitter enforces this while expanded

        # Main layout
        # Each section is a CARD in the V3 render — its own rounded surface,
        # separated from its neighbours by a gap, rather than a run of flat rows
        # with only a tinted header strip to tell one section from the next. The
        # card is what makes "these five rows belong to History" readable at a
        # glance, which matters most in the section this rail exists to make
        # scannable.
        self.setObjectName("sidebarSection")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _theme.style(self, "SIDEBAR_SECTION_CARD")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Header
        self.create_header()

        # Content container — Expanding so it fills the section's splitter allocation
        self.content_widget = QWidget()
        self.content_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(5, 5, 5, 5)
        self.content_layout.setSpacing(4)
        self.main_layout.addWidget(self.content_widget, 1)

        # Create section-specific content
        self.create_content()

    def news(self) -> str:
        """What this section has to SAY right now, or ``""`` when nothing.

        **A count is inventory; ``+9 eps`` is news.** Inventory tells you how
        much you own, news tells you something changed — and only one of those
        is worth a glance (R1, owner's words). So a section that has news
        surfaces it in its header INSTEAD of a bare number, and gets a bounded
        extra height allowance while it holds it.

        Sections override. The default is silence, which is right for
        Favorites and History: nothing about them is ever new.
        """
        return ""

    def item_count(self) -> int | None:
        """Rows this section holds, or ``None`` when a count says nothing.

        Shown in the header only when :meth:`news` is quiet — the two occupy
        the same slot, and news wins.
        """
        return None

    def header_status(self) -> str:
        """The text in the header's right-hand slot: news if any, else a count."""
        headline = self.news()
        if headline:
            return headline
        count = self.item_count()
        return "" if count is None else str(count)

    def min_expanded_height(self) -> int:
        """Smallest height at which this section still shows useful content.

        Derived from :attr:`MIN_ROWS` rather than shared, so "History needs four
        rows" is stated once, next to History, instead of being an emergent
        property of splitter arithmetic — the owner's saved layout had History
        at 91px against Watch Queue's 403px, which was not a preference.

        A section holding news earns :attr:`NEWS_BOOST_ROWS` more, so Alerts
        widens exactly when it has something to say.
        """
        rows = self.MIN_ROWS + (self.NEWS_BOOST_ROWS if self._news_active else 0)
        return max(_MIN_EXPANDED, self.HEADER_H + rows * self.ROW_H + 8)

    def _build_clickable_header(self) -> "_ClickableHeader":
        """Create and return a ``_ClickableHeader`` pre-wired with the toggle button.

        Subclasses that override ``create_header`` call this helper to get a header
        widget whose click → ``toggle_collapse`` wiring is already done.  They then
        add their own title label and any extra action buttons into the returned
        header's layout, and finish with::

            self.main_layout.addWidget(header)

        The toggle button is stored as ``self.toggle_btn`` on exit so the existing
        ``set_collapsed`` bookkeeping that updates ``toggle_btn.setText(…)`` continues
        to work unmodified.

        Returns:
            A ``_ClickableHeader`` instance with a ``QHBoxLayout`` (margins 5,3,5,3)
            already containing ``self.toggle_btn``.
        """
        header = _ClickableHeader()
        # Stashed so refresh_theme() can re-apply SECTION_HEADER_TINT after a
        # live palette switch — this is a local var otherwise, and every
        # subclass routes through this one helper to build its header.
        self._header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)

        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.setToolTip("Collapse / expand this section")
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_btn)

        # Clicking anywhere on the header (outside child buttons) also toggles.
        header.clicked.connect(self.toggle_collapse)

        return header

    def _add_explore_link(self, header_layout: QHBoxLayout) -> QPushButton | None:
        """Append the shared Explore (→) header button, when this section has one.

        The ONE definition of the affordance (glyph, style, tooltip, signal):
        History, Favorites, Watch Queue and Recommended all get their link from here
        rather than each building its own.  Sections opt in by setting
        :attr:`EXPLORE_KEY` to their :data:`~metatv.gui.explore_view.EXPLORE_SOURCES`
        key — the tooltip comes from that source, so the rail and the view it opens
        can never describe themselves differently.

        Icon-only (owner: "maybe there are too many 'Explore' words on the side
        panel now").  Four sections stacked vertically repeated the same word four
        times, which stops being read and is pure crowding — more so now the Watch
        Queue header also carries a 🔍.  The tooltip ("Explore your Watch Queue…")
        carries the name.

        The glyph is ``explore_columns_icon`` (⤢) — the affordance that opened the
        cascading columns from a Similar row before click-to-preview replaced it
        there, so it is already learned for exactly this action.  NOT
        ``expand_icon``: the collapse toggle in this very header renders that pair
        (``>``/``⌄``), and two identical glyphs in one header meaning different
        things is worse than the crowding this removes.

        A ``QPushButton`` consumes its own click, so the link never toggles the
        collapsible header underneath it.

        Args:
            header_layout: The header's layout, from ``_build_clickable_header()``.

        Returns:
            The button (stored as ``self.explore_btn``), or None when the section
            has no ``EXPLORE_KEY``.
        """
        if not self.EXPLORE_KEY:
            return None
        # Local imports: explore_view pulls in the trail-map widget, and the sidebar
        # package is imported while MainWindow is still being built.
        from metatv.gui import icons as _icons
        from metatv.gui.explore_view import EXPLORE_SOURCES

        btn = QPushButton(_icons.explore_columns_icon)
        btn.setFlat(True)
        btn.setFixedSize(22, 20)  # structural — aligns with the other header buttons
        btn.setToolTip(EXPLORE_SOURCES[self.EXPLORE_KEY].link_tooltip)
        _theme.style(btn, "SIDEBAR_SEE_ALL_BTN")
        # Resolve the bound signal at CLICK time, not build time.  create_header runs
        # before Qt's C++ side is guaranteed up in the header unit-tests (sections are
        # built via __new__ there), and `self.exploreClicked` would raise
        # "super-class __init__() was never called" the moment it is dereferenced.
        # The lambda keeps header construction independent of Qt init order.
        btn.clicked.connect(lambda: self.exploreClicked.emit())
        header_layout.addWidget(btn)
        self.explore_btn = btn
        return btn

    def header_tint(self) -> str | None:
        """Colour for the header icon, or ``None`` for the default text colour.

        A method rather than a constructor argument on purpose: it is called
        from inside the ``style_fn`` builder, so overriding it with a live token
        read (``_theme.COLOR_GOLD``) re-resolves on every palette switch. A
        value passed in at construction would be the old palette's hex forever.
        """
        return None

    def _title_html(self) -> str:
        """The header's icon-and-title rich text for the CURRENT palette."""
        if self.vector_role:
            glyph = _icon_utils.inline_icon_html(
                _icons.vector_key(self.vector_role),
                self.header_tint() or _theme.COLOR_TEXT,
            )
            if glyph:
                return f"{glyph} <b>{self.title}</b>"
        # No role, or the icon pack failed to resolve — keep the emoji.
        return f"{self.icon} <b>{self.title}</b>"

    def make_title_label(self) -> QLabel:
        """Build the header title label and keep its icon on-palette.

        The single place a section header's title is constructed. Five sections
        had grown their own copy of this line, which is how the gold Favorites
        star and the plain ones drifted apart in the first place; a new header
        affordance now lands in one file instead of five.

        Registered through ``theme.style_fn`` because that is what a palette
        switch re-invokes — and re-rendering the glyph is the whole point, since
        an already-rasterised PNG cannot change colour on its own.
        """
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)

        def _build() -> str:
            label.setText(self._title_html())
            return ""      # the label carries no sheet of its own

        _theme.style_fn(label, _build)
        return label

    def make_status_label(self) -> QLabel:
        """The header's right-hand slot — news, or a count, or nothing.

        One label for both so they can never both appear: they are alternatives,
        not a pair, and a header showing ``1 new  ·  13`` is back to being
        inventory with a decoration.

        Registered through ``theme.style_fn`` so a palette switch re-colours it;
        news is painted in the accent because it is the one thing in a collapsed
        sidebar worth looking at.
        """
        label = self._status_label = QLabel()

        def _build() -> str:  # noqa: D401 — a style_fn builder
            self._news_active = bool(self.news())
            text = self.header_status()
            label.setText(text)
            label.setVisible(bool(text))
            # COLOR_ACCENT_BLUE, not COLOR_ACCENT. The distinction is already
            # documented at PLAY_BTN: COLOR_ACCENT is the accent as a FILL, and
            # as TEXT on the app surface it is a midtone — 2.61:1 in Graphite.
            # That made a section WITH news less readable than one without
            # (news 2.61:1 against plain 3.76:1), which is the signal exactly
            # backwards. COLOR_ACCENT_BLUE is the accent-as-text member and
            # clears 7.3:1 or better in every palette, always above MUTED.
            colour = _theme.COLOR_ACCENT_BLUE if self.news() else _theme.COLOR_MUTED
            return f"color: {colour}; font-size: {_theme.FONT_SM};"

        self._status_build = _build
        _theme.style_fn(label, _build)
        return label

    def refresh_header_status(self) -> None:
        """Re-read :meth:`news`/:meth:`item_count` into the header.

        Called by a section whenever its contents change. Also re-applies the
        section's minimum height, because gaining or losing news changes it —
        that is the news boost taking effect (R13, mechanism 3).
        """
        # Re-run the registered builder rather than reaching for a theme-level
        # "reapply one widget" that does not exist: the builder is what sets
        # the TEXT as well as the sheet, so re-invoking it is the update.
        label = self.__dict__.get("_status_label")
        build = self.__dict__.get("_status_build")
        if label is not None and build is not None:
            label.setStyleSheet(build())
        try:
            self.setMinimumHeight(
                self.HEADER_H if self.is_collapsed else self.min_expanded_height()
            )
        except RuntimeError:
            # A ``__new__``'d section (several tests drive the real update
            # methods on one) has no C++ side to resize. The header state above
            # is still worth updating; the floor is not, because there is no
            # splitter for it to act on.
            pass

    def create_header(self):
        """Create collapsible header with title and toggle button."""
        header = self._build_clickable_header()
        header_layout = header.layout()

        self.title_label = self.make_title_label()
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.make_status_label())
        self._add_header_actions(header_layout)
        self._add_explore_link(header_layout)

        self.main_layout.addWidget(header)

    def _add_header_actions(self, header_layout: QHBoxLayout) -> None:
        """Hook: append section-specific buttons left of the "Explore →" link.

        Exists so a section that needs one extra header control does not have to
        re-implement ``create_header`` and carry a divergent copy of the title /
        stretch / explore wiring (the shared-core rule). Default: nothing.
        """
        return None

    def create_content(self):
        """Override in subclasses to add section-specific content"""
        pass

    def toggle_collapse(self):
        """Toggle collapsed/expanded state"""
        self._user_collapsed = not self.is_collapsed  # record user intent before toggling
        self.set_collapsed(not self.is_collapsed)

    def set_collapsed(self, collapsed: bool, save: bool = True):
        """Set collapsed state.

        Args:
            collapsed: Whether to collapse the section.
            save: Whether to save state and redistribute splitter space (False during restore).
        """
        self.is_collapsed = collapsed
        self.content_widget.setVisible(not collapsed)

        if collapsed:
            self.toggle_btn.setText(self.config.expand_icon)
            h = self.height()
            if h >= self.min_expanded_height():
                self._expanded_height = h
            freed = max(0, h - 26)
            self.setMinimumHeight(26)
            self.setMaximumHeight(self.minimumSizeHint().height())
            if save and freed > 0:
                self._release_in_splitter(freed)
        else:
            self.toggle_btn.setText(self.config.collapse_icon)
            self.setMinimumHeight(self.min_expanded_height())
            self.setMaximumHeight(16777215)  # Qt's QWIDGETSIZE_MAX
            if save:
                self._grow_in_splitter()

        # Notify parent to adjust layout
        self.updateGeometry()
        self.sizeChanged.emit()

        # Save state (unless explicitly disabled, e.g. during restore)
        if save:
            self.save_state()

    # ------------------------------------------------------------------
    # Splitter redistribution helpers
    # ------------------------------------------------------------------

    def _grow_in_splitter(self) -> None:
        """Grow to saved expanded height, stealing proportionally from neighbors."""
        from PyQt6.QtWidgets import QSplitter
        splitter = self.parentWidget()
        if not isinstance(splitter, QSplitter):
            return

        idx = splitter.indexOf(self)
        sizes = list(splitter.sizes())
        n = len(sizes)
        if idx < 0 or idx >= n:
            return

        target = max(self.min_expanded_height(), self._expanded_height)
        if sizes[idx] >= target:
            return

        # Floor for each other section: header-only if collapsed, _MIN_EXPANDED if expanded
        floors = [
            26 if getattr(splitter.widget(i), 'is_collapsed', False)
            else _floor_of(splitter.widget(i))
            for i in range(n)
        ]

        others_avail = [
            (i, max(0, sizes[i] - floors[i]))
            for i in range(n)
            if i != idx and sizes[i] > 0
        ]
        total_avail = sum(a for _, a in others_avail)
        if total_avail <= 0:
            return

        delta = min(target - sizes[idx], total_avail)
        new_sizes = list(sizes)
        new_sizes[idx] += delta

        remaining = delta
        for i, avail in sorted(others_avail, key=lambda x: -x[1]):
            if total_avail > 0 and avail > 0:
                take = round(delta * avail / total_avail)
                take = min(take, new_sizes[i] - floors[i], remaining)
                take = max(0, take)
                new_sizes[i] -= take
                remaining -= take

        if remaining > 0:
            for i, avail in others_avail:
                extra = min(remaining, new_sizes[i] - floors[i])
                if extra > 0:
                    new_sizes[i] -= extra
                    remaining -= extra
                if remaining <= 0:
                    break

        splitter.setSizes(new_sizes)

    def _release_in_splitter(self, freed: int) -> None:
        """Distribute freed pixels to other visible sections when this one collapses."""
        from PyQt6.QtWidgets import QSplitter
        splitter = self.parentWidget()
        if not isinstance(splitter, QSplitter):
            return

        idx = splitter.indexOf(self)
        sizes = list(splitter.sizes())
        n = len(sizes)
        if idx < 0 or idx >= n or freed <= 0:
            return

        recipients = [(i, sizes[i]) for i in range(n) if i != idx and sizes[i] > 0]
        if not recipients:
            return

        total_r = sum(s for _, s in recipients)
        new_sizes = list(sizes)
        new_sizes[idx] = 26  # collapsed to header height

        remaining = freed
        for i, s in sorted(recipients, key=lambda x: -x[1]):
            if total_r > 0:
                take = round(freed * s / total_r)
                take = min(take, remaining)
                new_sizes[i] += take
                remaining -= take

        if remaining > 0:
            for i, _ in recipients:
                new_sizes[i] += remaining
                remaining = 0
                break

        splitter.setSizes(new_sizes)

    # ------------------------------------------------------------------
    # Empty / state management
    # ------------------------------------------------------------------

    def show_load_error(self, list_widget, message: str) -> None:
        """Render a distinct, non-selectable error row after a failed background load.

        A failed background refresh must never look like a legitimate empty result
        (see CLAUDE.md "Background refresh failure must be visible"). Keeps the section
        expanded so the message is seen instead of silently blanking the list.
        """
        from PyQt6.QtWidgets import QListWidgetItem
        from metatv.gui import icons as _icons

        list_widget.clear()
        item = QListWidgetItem(f"{_icons.notification_warning_icon} {message}")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(item)
        self.set_empty(False)

    def show_loading(self, list_widget, message: str = "Loading…") -> None:
        """Render a transient, non-selectable loading row while a background load runs.

        Mirrors ``show_load_error`` exactly (same non-selectable row, same set_empty
        bookkeeping) but uses ``icons.loading_icon`` instead of the warning icon. Keeps
        the section expanded so the placeholder is visible instead of the section
        showing its stale empty/zero state during the load window. Replaced when the
        result slot clears the list and renders rows.
        """
        from PyQt6.QtWidgets import QListWidgetItem
        from metatv.gui import icons as _icons

        list_widget.clear()
        item = QListWidgetItem(f"{_icons.loading_icon} {message}")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        list_widget.addItem(item)
        self.set_empty(False)

    def set_empty(self, empty: bool):
        """Set empty state and auto-collapse if empty"""
        was_empty = self.is_empty
        self.is_empty = empty

        # Auto-collapse when becoming empty
        if empty and not was_empty:
            self.set_collapsed(True)
        # Auto-expand only when section was empty-collapsed (not user/restore-collapsed)
        elif not empty and was_empty and self.is_collapsed and not self._user_collapsed:
            self.set_collapsed(False)

    def get_section_id(self):
        """Get unique ID for this section (for saving state)"""
        # Override in subclasses or use title as default
        return self.title.lower().replace(" ", "_")

    def save_state(self):
        """Save section state to config"""
        section_id = self.get_section_id()

        # Get or create section states dict in config
        if not hasattr(self.config, 'sidebar_section_states'):
            self.config.sidebar_section_states = {}

        self.config.sidebar_section_states[section_id] = {
            'collapsed': self.is_collapsed,
            'height': self.height(),
            'expanded_height': self._expanded_height,
        }

        # Save config to disk
        try:
            self.config.save()
        except Exception as e:
            logger.warning(f"Could not save section state: {e}")

    def restore_state(self):
        """Restore section state from config"""
        section_id = self.get_section_id()

        if not hasattr(self.config, 'sidebar_section_states'):
            return

        state = self.config.sidebar_section_states.get(section_id)
        if state:
            # Restore saved expanded height first
            eh = state.get('expanded_height', _MIN_EXPANDED)
            if eh and eh >= _MIN_EXPANDED:
                self._expanded_height = eh
            # Restore collapsed state (don't redistribute during restore — saved sizes handle it)
            collapsed = state.get('collapsed', False)
            if collapsed:
                self._user_collapsed = True  # treat restored-collapsed as explicit user intent
            self.set_collapsed(collapsed, save=False)

    def refresh(self):
        """Refresh section content - override in subclasses"""
        pass

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this section's persistent chrome —
        the collapsible header and its "Explore →" link, both styled once at
        construction time (``setStyleSheet`` caches the rendered string, so a
        later ``theme.apply_theme()`` call doesn't repaint them on its own).

        Row/list content built by ``refresh()`` already reads whatever theme
        token values are current each time it rebuilds, so it doesn't need a
        sweep here — only the two widgets built directly by
        ``CollapsibleSection``/``_build_clickable_header`` do.  Called from
        ``MainWindow.refresh_theme()``'s sidebar sweep.
        """
        if hasattr(self, "_header"):
            _theme.style(self._header, "SECTION_HEADER_TINT")
        explore_btn = getattr(self, "explore_btn", None)
        if explore_btn is not None:
            _theme.style(explore_btn, "SIDEBAR_SEE_ALL_BTN")

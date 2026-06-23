"""WeightedTagCloud — a data-driven flow-layout tag cloud widget.

Displays facet values as clickable buttons sized by catalogue weight.  Font
size is log-bucketed across six tiers defined in theme.FONT_CLOUD_* so the
full range of counts maps visually to a readable large-to-small gradient.

Public API:
    set_tags(items, facet_color, facet_name="") -> None
    tag_clicked = pyqtSignal(str)   # emits the value string

Layout:
    ┌──────────────────────────────────────┐
    │ <Facet> · N values · sized by weight │ [Weight ↔ A-Z] [Filter…]
    ├──────────────────────────────────────┤
    │  tag₁  tag₂  tag₃  …               │  ← flow layout, wrapping
    │  [+ N more]                          │
    └──────────────────────────────────────┘

Top 40 tags are shown by default; "+N more" expands to show all.
"""

from __future__ import annotations

import math

from loguru import logger
from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

# Maximum number of tags shown before the "+N more" cap button appears.
_CAP: int = 40

# ── font-size token ladder ───────────────────────────────────────────────────────
_CLOUD_TOKENS: list[str] = [
    _theme.FONT_CLOUD_1,
    _theme.FONT_CLOUD_2,
    _theme.FONT_CLOUD_3,
    _theme.FONT_CLOUD_4,
    _theme.FONT_CLOUD_5,
    _theme.FONT_CLOUD_6,
]


def _count_to_font_token(count: int, min_count: int, max_count: int) -> str:
    """Map *count* onto one of the six FONT_CLOUD_* tokens using log scaling.

    When all counts are equal (flat distribution) every tag gets FONT_CLOUD_3
    (the middle tier).  The log base is chosen so the full min…max spread maps
    evenly across buckets 0–5.

    Args:
        count:     The raw catalogue count for this tag.
        min_count: Minimum count in the current set.
        max_count: Maximum count in the current set.

    Returns:
        One of the FONT_CLOUD_* token strings from ``metatv.gui.theme``.
    """
    n = len(_CLOUD_TOKENS)
    if max_count <= min_count:
        # Flat distribution — pick middle tier
        return _CLOUD_TOKENS[n // 2]
    # Use log₁₀ to compress the range; clip to [0, n-1]
    log_min = math.log10(max(1, min_count))
    log_max = math.log10(max(1, max_count))
    log_val = math.log10(max(1, count))
    if log_max == log_min:
        bucket = n // 2
    else:
        fraction = (log_val - log_min) / (log_max - log_min)
        bucket = min(n - 1, int(fraction * n))
    return _CLOUD_TOKENS[bucket]


def _fmt_count(n: int) -> str:
    """Format a raw count compactly: 286000 → '286k', 1100 → '1.1k', 240 → '240'.

    Args:
        n: Non-negative integer count.

    Returns:
        A short string representation.
    """
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{v:.0f}m" if v == int(v) else f"{v:.1f}m"
    if n >= 1_000:
        v = n / 1_000
        return f"{v:.0f}k" if v == int(v) else f"{v:.1f}k"
    return str(n)


# ── private flow layout (reused from discover_card._FlowLayout pattern) ──────────

class _FlowLayout:
    """Simple flow-layout helper — arranges widgets left-to-right, wrapping.

    This is the same layout primitive used by ``discover_card._FlowLayout``;
    see that module for the full design rationale.  We define our own copy here
    rather than importing the private class from ``discover_card`` so this widget
    has no coupling to the Discover subsystem.
    """

    def __init__(self, container: QWidget, h_spacing: int = 6, v_spacing: int = 4) -> None:
        self._container = container
        self._items: list[QWidget] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def add(self, widget: QWidget) -> None:
        widget.setParent(self._container)
        self._items.append(widget)

    def relayout(self, available_width: int) -> int:
        """Position all cloud-visible items within *available_width*.

        Uses ``cloud_visible`` (a ``_TagButton`` attribute) rather than
        ``isVisible()`` because headless Qt widgets always report
        ``isVisible() == False`` regardless of ``show()``/``hide()`` calls.

        Returns the total height occupied.
        """
        x, y, row_h = 0, 0, 0
        hs = self._h_spacing
        vs = self._v_spacing
        for w in self._items:
            # Use cloud_visible if available (TagButton), else fall back to isVisible
            logically_visible = getattr(w, "cloud_visible", w.isVisible())
            if not logically_visible:
                continue
            ww = w.sizeHint().width()
            wh = w.sizeHint().height()
            if x + ww > available_width and x > 0:
                x = 0
                y += row_h + vs
                row_h = 0
            w.setGeometry(QRect(x, y, ww, wh))
            x += ww + hs
            row_h = max(row_h, wh)
        return y + row_h if self._items else 0

    def clear(self) -> None:
        for w in self._items:
            w.deleteLater()
        self._items.clear()


# ── tag button ────────────────────────────────────────────────────────────────────

class _TagButton(QPushButton):
    """A single tag-cloud button: mark · value count.

    The button is sized by ``font_token`` (one of FONT_CLOUD_1..6); the label
    text and appearance vary by ``state``.

    Attributes:
        cloud_visible: Tracks whether this button is logically visible within
            the cloud (passes filter + within cap).  Used instead of
            ``isVisible()`` because headless (unshown) Qt widgets always report
            ``isVisible() == False`` regardless of ``show()``/``hide()`` calls
            on the child.
    """

    def __init__(
        self,
        value: str,
        count: int,
        state: str,
        font_token: str,
        facet_color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = value
        self.cloud_visible: bool = True   # logical visibility within the cloud

        # Build label: [mark] value countfmt
        mark = ""
        if state == "include":
            mark = _icons.tag_include_icon + " "
        elif state == "exclude":
            mark = _icons.tag_exclude_icon + " "

        count_str = _fmt_count(count)
        label = f"{mark}{value} {count_str}"
        self.setText(label)

        # State-specific color for the mark character only isn't trivially
        # achievable via a stylesheet; we colorize the whole button by state
        # and let the value color dominate.
        if state == "include":
            color = _theme.COLOR_OK
        elif state == "exclude":
            color = _theme.COLOR_WARN
        else:
            color = facet_color

        self.setStyleSheet(
            f"QPushButton {{ font-size: {font_token}; color: {color};"
            f" border: 1px solid {_theme.COLOR_BORDER}; border-radius: 4px;"
            f" padding: 2px 6px; background: transparent; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_HI};"
            f" border-color: {_theme.COLOR_DIM}; background: {_theme.OVERLAY_05}; }}"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{value} — {count:,} channels")
        self.adjustSize()

    def value(self) -> str:
        return self._value

    def set_cloud_visible(self, visible: bool) -> None:
        """Set both the logical cloud_visible flag and the Qt widget visibility."""
        self.cloud_visible = visible
        if visible:
            self.show()
        else:
            self.hide()


# ── flow container ────────────────────────────────────────────────────────────────

class _CloudBody(QWidget):
    """The flow-layout body of the cloud.

    Owns _FlowLayout and reflows on every resize event.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flow = _FlowLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def flow(self) -> _FlowLayout:
        return self._flow

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        h = self._flow.relayout(self.width())
        self.setFixedHeight(max(1, h))

    def refresh_layout(self) -> None:
        h = self._flow.relayout(self.width())
        self.setFixedHeight(max(1, h))


# ── main widget ───────────────────────────────────────────────────────────────────

class WeightedTagCloud(QWidget):
    """Data-driven tag cloud with log-bucketed font sizing.

    Usage:
        cloud = WeightedTagCloud()
        cloud.tag_clicked.connect(on_tag)
        cloud.set_tags(
            items=[("Action", 1200, "none"), ("Drama", 860, "include"), ...],
            facet_color=theme.COLOR_ACCENT_TEAL,
            facet_name="Genre",
        )

    The widget is stateless about include/exclude logic — it only renders the
    ``state`` passed in and emits ``tag_clicked`` when a button is activated.
    The caller is responsible for toggling state and calling ``set_tags`` again.

    Attributes:
        _tag_buttons: Live list of ``_TagButton`` instances after the last
            ``set_tags`` call.  Exposed so tests can introspect the rendered
            cloud without reaching into the widget hierarchy by type.
    """

    tag_clicked = pyqtSignal(str)   # emits the value string

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sort_az: bool = False          # False = weight (default), True = A-Z
        self._filter_text: str = ""
        self._all_items: list[tuple[str, int, str]] = []   # (value, count, state)
        self._facet_color: str = _theme.COLOR_TEXT
        self._facet_name: str = ""
        self._cap_expanded: bool = False

        # Public attribute for test introspection
        self._tag_buttons: list[_TagButton] = []

        self._build_ui()

    # ── public API ────────────────────────────────────────────────────────────

    def set_tags(
        self,
        items: list[tuple[str, int, str]],
        facet_color: str,
        facet_name: str = "",
    ) -> None:
        """Populate the cloud with a new set of tag items.

        Args:
            items:       List of ``(value, count, state)`` tuples where
                         ``state`` is one of ``"none"``, ``"include"``,
                         ``"exclude"``.
            facet_color: A theme token value used as the text color for
                         ``state == "none"`` tags.
            facet_name:  Optional facet label shown in the header (e.g.
                         ``"Genre"``).  Falls back to ``""`` when omitted.
        """
        self._all_items = list(items)
        self._facet_color = facet_color
        self._facet_name = facet_name
        self._cap_expanded = False   # reset on new data

        self._update_header()
        self._rebuild_cloud()

    # ── private: UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Header row
        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)

        self._header_lbl = QLabel("")
        self._header_lbl.setStyleSheet(_theme.CLOUD_HEADER_LABEL)
        hl.addWidget(self._header_lbl)

        hl.addStretch()

        # Sort toggle (checkable: unchecked = Weight, checked = A-Z)
        self._sort_btn = QPushButton(f"{_icons.sort_icon} Weight")
        self._sort_btn.setCheckable(True)
        self._sort_btn.setChecked(False)
        self._sort_btn.setStyleSheet(_theme.CLOUD_CTRL_BTN)
        self._sort_btn.setToolTip(
            "Sort by catalogue weight (descending count) — click for A-Z sort"
        )
        self._sort_btn.toggled.connect(self._on_sort_toggled)
        hl.addWidget(self._sort_btn)

        # Filter search box
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter…")
        self._filter_edit.setFixedWidth(120)
        self._filter_edit.setStyleSheet(
            f"QLineEdit {{ font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT};"
            f" background: {_theme.OVERLAY_05}; border: 1px solid {_theme.COLOR_BORDER};"
            f" border-radius: 3px; padding: 1px 6px; }}"
        )
        self._filter_edit.setToolTip("Filter tags by name — live substring match")
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        hl.addWidget(self._filter_edit)

        outer.addWidget(header)

        # Cloud body
        self._body = _CloudBody()
        outer.addWidget(self._body)

        # "+N more" cap button (hidden until needed)
        self._more_btn = QPushButton("")
        self._more_btn.setStyleSheet(_theme.CLOUD_MORE_BTN)
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.cloud_visible = False   # track logical visibility
        self._more_btn.hide()
        self._more_btn.clicked.connect(self._on_expand_more)
        outer.addWidget(self._more_btn)

        # Absorb leftover vertical space at the bottom so the header + tags stay
        # top-aligned.  Without this, a tall parent slot (the recipe stage gives
        # the cloud stretch=1) makes QVBoxLayout smear the empty space *between*
        # the header and the tag body — the large dead gap above the tags.
        outer.addStretch(1)

    # ── private: header ───────────────────────────────────────────────────────

    def _update_header(self) -> None:
        n = len(self._all_items)
        facet = self._facet_name or "Tags"
        self._header_lbl.setText(
            f"{facet} · {n} values · sized by catalogue weight"
        )

    # ── private: sort / filter ────────────────────────────────────────────────

    def _on_sort_toggled(self, checked: bool) -> None:
        self._sort_az = checked
        self._sort_btn.setText(
            f"{_icons.sort_icon} A-Z" if checked else f"{_icons.sort_icon} Weight"
        )
        self._sort_btn.setToolTip(
            "Sort A-Z — click for weight sort"
            if checked
            else "Sort by catalogue weight (descending count) — click for A-Z sort"
        )
        self._rebuild_cloud()

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        self._apply_filter()

    # ── private: cloud building ───────────────────────────────────────────────

    def _sorted_items(self) -> list[tuple[str, int, str]]:
        """Return items sorted according to the current sort mode."""
        if self._sort_az:
            return sorted(self._all_items, key=lambda t: t[0].lower())
        return sorted(self._all_items, key=lambda t: t[1], reverse=True)

    def _rebuild_cloud(self) -> None:
        """Destroy all existing tag buttons and build fresh ones."""
        self._tag_buttons = []
        self._body.flow().clear()

        items = self._sorted_items()
        if not items:
            self._more_btn.hide()
            self._body.refresh_layout()
            return

        counts = [c for _, c, _ in items]
        min_count = min(counts)
        max_count = max(counts)

        for value, count, state in items:
            token = _count_to_font_token(count, min_count, max_count)
            btn = _TagButton(value, count, state, token, self._facet_color)
            btn.clicked.connect(self._make_click_handler(value))
            self._body.flow().add(btn)
            self._tag_buttons.append(btn)

        # _apply_filter() calls _update_cap() internally — no need to call it twice.
        self._apply_filter()

    def _make_click_handler(self, value: str):
        """Closure factory so each button captures its own value."""
        def _handler() -> None:
            logger.debug(f"WeightedTagCloud: tag clicked: {value!r}")
            self.tag_clicked.emit(value)
        return _handler

    def _apply_filter(self) -> None:
        """Show/hide tag buttons based on current filter text.

        Sets ``cloud_visible`` (logical state) + calls Qt show()/hide() so
        both headless-test assertions and real Qt layout stay in sync.
        """
        q = self._filter_text
        for btn in self._tag_buttons:
            matches = (not q) or (q in btn.value().lower())
            btn.set_cloud_visible(matches)
        self._update_cap()

    def _update_cap(self) -> None:
        """Apply the top-40 cap and update the '+N more' button.

        Uses ``cloud_visible`` (not ``isVisible()``) so the cap works
        correctly in both headless tests and shown windows.
        """
        if self._cap_expanded:
            # Already expanded — ensure all filter-matching buttons are visible
            self._more_btn.cloud_visible = False
            self._more_btn.hide()
            self._body.refresh_layout()
            return

        filter_visible = [b for b in self._tag_buttons if b.cloud_visible]
        total_visible = len(filter_visible)

        if total_visible <= _CAP:
            self._more_btn.cloud_visible = False
            self._more_btn.hide()
        else:
            # Hide overflow buttons (beyond first _CAP within filter-matches)
            for btn in filter_visible[_CAP:]:
                btn.set_cloud_visible(False)
            overflow = total_visible - _CAP
            self._more_btn.setText(
                f"{_icons.show_all_icon} +{overflow} more"
            )
            self._more_btn.setToolTip(
                f"Show all {total_visible} matching tags — {overflow} hidden"
            )
            self._more_btn.cloud_visible = True
            self._more_btn.show()

        self._body.refresh_layout()

    def _on_expand_more(self) -> None:
        """Reveal all hidden overflow tag buttons."""
        self._cap_expanded = True
        q = self._filter_text
        for btn in self._tag_buttons:
            # Re-show all buttons that match the current filter
            if (not q) or (q in btn.value().lower()):
                btn.set_cloud_visible(True)
        self._more_btn.cloud_visible = False
        self._more_btn.hide()
        self._body.refresh_layout()

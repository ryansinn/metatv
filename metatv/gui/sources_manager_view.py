"""Sources manager — full-view provider list + configuration (Wave 6, Wave 7).

Replaces the old sidebar ``SourcesSection``. Opened from the sidebar status
strip (``gui/sidebar/sources_strip.py``).

TOP: every provider as a chip in a wrapping strip (owner, 2026-10-31 — it
replaced a fixed 280 px left column, mostly empty height for the three to five
sources most people have, that took width from the editor). A chip is icon ·
status dot · the first 14 characters of the name, with "expired" / "disabled" /
days left on a smaller second line; the full name is on hover. Every action
lives in the embedded editor's Summary-tab action bar; this view's public
``providerToggleClicked``/``providerEpgRefreshClicked`` signals fire from it via
the pass-through connections in ``__init__``. Refresh fires straight off the
editor's own ``refresh_requested`` (connected in ``main_window.py``).

BELOW, full width: the host's single ``ProviderEditorView`` instance, embedded here
instead of added directly to the content stack — never a second instance /
parallel save-delete-refresh plumbing. Selecting a chip calls
``load_provider()`` on it directly (in-view, no separate "edit mode" switch).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from metatv.core.repositories import RepositoryFactory
from metatv.gui import cursor_affordance
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import theme as _theme
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.subscription_status import source_status_dot, subscription_color

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database


#: Characters of a source's name a chip shows before "…" (owner, 2026-10-31).
CHIP_NAME_CHARS = 14


def chip_name(name: str) -> str:
    """The first CHIP_NAME_CHARS characters of *name*, "…" when cut."""
    return name if len(name) <= CHIP_NAME_CHARS else name[:CHIP_NAME_CHARS].rstrip() + "…"


def chip_subline(is_active: bool, exp_date: "datetime | None", now: datetime) -> str:
    """The chip's second line, in words: "expired", "disabled · 27 days left",
    "27 days left", "disabled" or "" — the state the dot shows, said too."""
    if exp_date is not None and exp_date <= now:
        return "expired"
    parts = [] if is_active else ["disabled"]
    if exp_date is not None:
        days = (exp_date - now).days
        parts.append(f"{days} day left" if days == 1 else f"{days} days left")
    return " · ".join(parts)


class _SourceChip(QPushButton):
    """One source in the strip: icon · status dot · name, days left beneath.

    A QPushButton for the press/hover/focus behaviour and the segmented
    selected/unselected roles; its two lines are a child layout the button
    sizes itself from (a QPushButton's own size hint only measures its text).
    The full name, state and expiry are on the tooltip.
    """

    #: provider_id — connected to the view's bound method, which PyQt holds
    #: weakly; a lambda capturing the view would keep it alive.
    chosen = pyqtSignal(str)

    def __init__(self, provider, now: datetime, parent=None) -> None:
        super().__init__(parent)
        self._provider_id = provider.id
        self.clicked.connect(self._on_clicked)
        is_expired = bool(provider.account_exp_date and provider.account_exp_date <= now)
        role, token, state = source_status_dot(bool(provider.is_active), is_expired)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 4, 10, 4)
        outer.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(5)
        icon = getattr(provider, "icon", "") or ""
        if icon:
            top.addWidget(QLabel(icon))
        dot = QLabel()
        _icon_utils.set_label_icon(dot, role, 10)
        _theme.style_fn(dot, lambda: f"color: {getattr(_theme, token)};")
        top.addWidget(dot)
        self.name_label = QLabel(chip_name(provider.name))
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(self.name_label)
        outer.addLayout(top)
        self.days_label = QLabel(chip_subline(bool(provider.is_active), provider.account_exp_date, now))
        exp, created = provider.account_exp_date, provider.account_created_at
        active = bool(provider.is_active)
        _theme.style_fn(self.days_label, lambda: (
            f"font-size: {_theme.FONT_SM}; color: "
            f"{(active and subscription_color(exp, created)) or _theme.COLOR_MUTED_2};"))
        self.days_label.setVisible(bool(self.days_label.text()))
        outer.addWidget(self.days_label)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.setToolTip(" · ".join(t for t in (provider.name, state, self.days_label.text()) if t))
        cursor_affordance.set_clickable(self)
        self.set_selected(False)

    def _on_clicked(self) -> None:
        self.chosen.emit(self._provider_id)

    def set_selected(self, selected: bool) -> None:
        _theme.style(self, "SEGMENTED_ACTIVE" if selected else "SEGMENTED_INACTIVE")

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return self.layout().minimumSize()


class SourcesManagerView(QWidget):
    """Main-area Sources manager: a strip of source chips over the editor.

    The chips replaced a fixed 280 px left column (owner, 2026-10-31): with the
    three to five sources most people have, that column was mostly empty
    height, and it took width from the editor where the detail lives.
    """

    providerToggleClicked = pyqtSignal(str)
    providerEpgRefreshClicked = pyqtSignal(str)
    addProviderClicked = pyqtSignal()

    def __init__(
        self, config: "Config", db: "Database", provider_editor: QWidget, parent=None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.db = db
        self._provider_editor = provider_editor
        # provider_ids with an operation in flight — survives refresh() rebuilds
        # (mirrors the retired SourcesSection's _busy_ids, same purpose).
        self._busy_ids: set[str] = set()
        self._chips: dict[str, _SourceChip] = {}
        self._selected_id: str | None = None

        self.setObjectName("sourcesManagerView")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        title = QLabel(f"{_icon_utils.role_html('provider')}&nbsp;<b>Sources</b>")
        header_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignTop)
        strip = QWidget()
        self._strip = FlowLayout(strip, spacing=6)
        self._strip.setContentsMargins(8, 0, 8, 0)
        header_layout.addWidget(strip, 1)

        self._add_btn = QPushButton("Add Source")
        _icon_utils.set_button_icon(self._add_btn, "add")
        self._add_btn.setMinimumHeight(28)
        self._add_btn.setToolTip("Add Source…")
        _theme.style(self._add_btn, "SOURCES_ADD_BTN")
        cursor_affordance.set_clickable(self._add_btn)
        self._add_btn.clicked.connect(self.addProviderClicked.emit)
        header_layout.addWidget(self._add_btn, 0, Qt.AlignmentFlag.AlignTop)
        outer.addWidget(header)

        center = QWidget()
        self._center_layout = QVBoxLayout(center)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.addWidget(self._provider_editor)

        # Pass-through wiring (Wave 7): the editor's action bar replaced the row
        # buttons as the source of these clicks — re-point by relaying the
        # editor's new per-action signals onto this view's EXISTING public
        # signals, so main_window.py's handler connections need no changes.
        # Refresh is the one exception: it reuses the editor's pre-existing
        # (previously unemitted) `refresh_requested` signal, already connected
        # directly to `self.refresh_provider` on this same embedded instance —
        # no pass-through needed here for it.
        self._provider_editor.toggle_active_requested.connect(self.providerToggleClicked.emit)
        self._provider_editor.epg_refresh_requested.connect(self.providerEpgRefreshClicked.emit)
        self._provider_editor.new_source_cancelled.connect(self._on_new_source_cancelled)

        self._empty_label = QLabel("Select a source above to view its configuration.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        _theme.style(self._empty_label, "EXPLORE_STATUS")
        self._center_layout.addWidget(self._empty_label)

        outer.addWidget(center, 1)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #
    def on_activate(self) -> None:
        """Rebuild the provider list and (re-)select a row.

        Keeps the previously-selected provider selected across re-activation
        when it still exists; otherwise falls back to the first row.
        """
        self.refresh()
        if self._selected_id and self._selected_id in self._chips:
            self.select_provider(self._selected_id)
        elif self._chips:
            self.select_provider(next(iter(self._chips)))

    def on_deactivate(self) -> None:
        """Hide the embedded editor so a stale form isn't visible under another
        view (the row selection itself is kept for next activation)."""
        self._provider_editor.setVisible(False)

    # ------------------------------------------------------------------ #
    # Selection                                                            #
    # ------------------------------------------------------------------ #
    def select_provider(self, provider_id: str) -> None:
        """Load *provider_id* into the embedded editor and highlight its row."""
        if provider_id not in self._chips:
            return
        self._selected_id = provider_id
        for pid, chip in self._chips.items():
            chip.set_selected(pid == provider_id)
        self._empty_label.setVisible(False)
        self._provider_editor.setVisible(True)
        self._provider_editor.load_provider(provider_id)
        # A busy toggle for this provider may have started while a different
        # row was selected (or before any row was) — resync the action bar's
        # busy visual so switching back to it mid-operation still shows it.
        self._provider_editor.set_toggle_busy(provider_id in self._busy_ids)

    def start_new_source(self) -> None:
        """Show the editor on a blank source: the one Add Source path."""
        for chip in self._chips.values():
            chip.set_selected(False)
        self._empty_label.setVisible(False)
        self._provider_editor.setVisible(True)
        self._provider_editor.start_new_source()

    def _on_new_source_cancelled(self) -> None:
        """Back to the previously selected source, or the empty prompt."""
        if self._selected_id and self._selected_id in self._chips:
            self._provider_editor.load_provider(self._selected_id, force=True)
            self.select_provider(self._selected_id)
        elif self._chips:
            self.select_provider(next(iter(self._chips)))
        else:
            self._provider_editor.setVisible(False)
            self._empty_label.setVisible(True)

    # ------------------------------------------------------------------ #
    # Data                                                                 #
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        """Rebuild the source chips from the database."""
        while self._strip.count():
            item = self._strip.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._chips = {}

        with self.db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            now = datetime.now()

            for provider in providers:
                chip = _SourceChip(provider, now)
                chip.chosen.connect(self.select_provider)
                self._strip.addWidget(chip)
                self._chips[provider.id] = chip

        if not providers:
            self._selected_id = None
            self._provider_editor.setVisible(False)
            self._empty_label.setText("No sources yet. Click + to add one.")
            self._empty_label.setVisible(True)

    # ------------------------------------------------------------------ #
    # Busy / EPG-spinner state — same external surface the retired sidebar
    # SourcesSection exposed, so MainWindow's existing call sites work
    # unchanged (see MainWindow._sources_status_target).
    # ------------------------------------------------------------------ #
    def is_provider_busy(self, provider_id: str) -> bool:
        return provider_id in self._busy_ids

    def set_provider_busy(self, provider_id: str, busy: bool) -> None:
        """Track busy state in ``_busy_ids`` (interface parity — still read by
        ``is_provider_busy``/``has_busy``/``clear_busy`` elsewhere) and, when
        *provider_id* is the one currently loaded in the editor, render the
        spinner on its action bar's Enable/Disable button — the row itself has
        no busy visual of its own since Wave 7 (``show_actions=False``)."""
        if busy:
            self._busy_ids.add(provider_id)
        else:
            self._busy_ids.discard(provider_id)
        if provider_id == self._selected_id:
            self._provider_editor.set_toggle_busy(busy)

    def set_provider_epg_refreshing(self, provider_id: str, busy: bool) -> None:
        """Render the EPG-refresh spinner on the editor's action bar "Refresh
        Guide" button when *provider_id* is the one currently loaded — mirrors
        the retired row EPG pip's spinner, which never persisted across a
        ``refresh()`` rebuild either (no ``_busy_ids``-style tracking needed)."""
        if provider_id == self._selected_id:
            self._provider_editor.set_epg_busy(busy)

    def has_busy(self) -> bool:
        return bool(self._busy_ids)

    def clear_busy(self) -> None:
        for pid in list(self._busy_ids):
            self.set_provider_busy(pid, False)

    def update_provider_status(self, provider_id: str, status: str) -> None:
        """Legacy no-op — kept for interface parity with the retired sidebar
        section; widgets update via refresh()/set_provider_busy()."""


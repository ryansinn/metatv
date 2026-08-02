"""Sources status strip — compact, always-visible summary above Settings.

Wave 6: Sources leaves the reorderable sidebar section stack.  This one-line
strip (NOT a ``CollapsibleSection``) is pinned above the Settings button and
shows a live "N active / M expiring" summary; clicking it opens the full
:class:`~metatv.gui.sources_manager_view.SourcesManagerView`.  The old
per-provider list/actions moved there — this widget only ever shows the
aggregate.

Reuses the SAME subscription-freshness classification the provider rows use
(``provider_editor.subscription_color`` — single source of truth), so "expiring"
here always agrees with the amber/red a source shows in the manager.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from metatv.core.repositories import RepositoryFactory
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.database import ProviderDB


def summarize_providers(providers: list["ProviderDB"], now: datetime) -> tuple[int, int]:
    """Classify providers into (active_count, expiring_count) for the strip text.

    'active' = enabled providers with no subscription concern (the green status
    dot elsewhere). 'expiring' = ANY provider — enabled or not — whose
    subscription has already lapsed or is running low, using the same
    ``subscription_color`` classification (WARN/ERR) the manager's rows use.

    Args:
        providers: Provider rows (ORM or any object exposing the same attrs).
        now: Current time (injected for deterministic tests).

    Returns:
        (active_count, expiring_count) — a provider that is simply disabled with
        no subscription concern is counted in neither.
    """
    from metatv.gui.provider_editor import subscription_color

    active = expiring = 0
    for p in providers:
        is_expired = bool(p.account_exp_date and p.account_exp_date <= now)
        color = (
            subscription_color(p.account_exp_date, p.account_created_at)
            if p.account_exp_date else ""
        )
        concerning = is_expired or color in (_theme.COLOR_WARN, _theme.COLOR_ERR)
        if concerning:
            expiring += 1
        elif p.is_active:
            active += 1
    return active, expiring


def _summary_text(active: int, expiring: int, total: int) -> str:
    """Build the one-line summary string (never encodes state by colour alone)."""
    if total == 0:
        return "No sources yet"
    parts = [f"{_icons.status_dot_icon} {active} active"]
    if expiring:
        parts.append(f"{_icons.notification_warning_icon} {expiring} expiring")
    return "   ·   ".join(parts)


class SourcesStatusStrip(QWidget):
    """One-line "Sources" summary + Refresh All, pinned above Settings.

    Emits ``clicked`` when the strip itself (not the Refresh button) is
    pressed — the host wires this to open the Sources manager view.
    """

    clicked = pyqtSignal()
    refreshAllClicked = pyqtSignal()

    def __init__(self, config: "Config", db: "Database", parent=None):
        super().__init__(parent)
        self.config = config
        self.db = db

        self.setObjectName("sourcesStatusStrip")
        self.setStyleSheet(_theme.SOURCES_STRIP)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("Open the Sources manager")
        cursor_affordance.set_clickable(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 8, 7)
        layout.setSpacing(6)

        title = QLabel(f"{_icons.provider_icon} Sources")
        title.setStyleSheet(_theme.SOURCES_STRIP_TITLE)
        layout.addWidget(title)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(_theme.CHANNEL_NAME_DIM)
        layout.addWidget(self._summary_lbl, 1)

        self._refresh_btn = QPushButton(_icons.refresh_icon)
        self._refresh_btn.setFixedSize(22, 20)
        self._refresh_btn.setFlat(True)
        self._refresh_btn.setToolTip("Refresh all sources")
        self._refresh_btn.setStyleSheet(_theme.RECIPE_SAVED_ICON_BTN)
        cursor_affordance.set_clickable(self._refresh_btn)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(self._refresh_btn)

        self.refresh()

    # ------------------------------------------------------------------ #
    # Interaction                                                          #
    # ------------------------------------------------------------------ #
    def _on_refresh_clicked(self) -> None:
        self.refreshAllClicked.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt override
        """A click anywhere on the strip except the Refresh button opens the
        manager. Qt routes the press to the button first when it's the target,
        so this only fires for the rest of the strip."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    # ------------------------------------------------------------------ #
    # State                                                                #
    # ------------------------------------------------------------------ #
    def set_busy(self, busy: bool) -> None:
        """Disable the Refresh All button while a refresh sweep is in flight
        (wired to ``RefreshQueueManager.queue_changed`` by the host)."""
        self._refresh_btn.setEnabled(not busy)
        self._refresh_btn.setToolTip("Refreshing sources…" if busy else "Refresh all sources")

    def refresh(self) -> None:
        """Recompute the active/expiring summary from live provider state.

        A synchronous small read (the ``providers`` table is a handful of rows,
        not a large corpus scan) — matches the existing sidebar-section
        precedent for this exact query.
        """
        with self.db.session_scope(commit=False) as session:
            providers = RepositoryFactory(session).providers.get_all()
            now = datetime.now()
            active, expiring = summarize_providers(providers, now)
            total = len(providers)
        self._summary_lbl.setText(_summary_text(active, expiring, total))

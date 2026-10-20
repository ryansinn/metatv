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
from typing import TYPE_CHECKING, NamedTuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from metatv.core.repositories import RepositoryFactory
from metatv.gui import cursor_affordance
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import theme as _theme

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.database import ProviderDB


class SourceSummary(NamedTuple):
    """What the strip knows about the sources, counted independently."""

    active: int
    expiring: int
    expired: int


def summarize_providers(providers: list["ProviderDB"], now: datetime) -> SourceSummary:
    """Classify providers for the strip text.

    'active' = enabled providers (the green status dot elsewhere), whatever
    their subscription is doing. 'expiring' = any provider, enabled or not,
    whose subscription is still running but low, using the same
    ``subscription_color`` classification (WARN/ERR) the manager's rows use.
    'expired' = an ENABLED provider past its date. A lapsed subscription is
    never "expiring" — it already happened — and a disabled source that has
    expired is settled, so it says nothing (the owner's install showed
    "2 expiring" for two sources that lapsed a month earlier and were off).

    Args:
        providers: Provider rows (ORM or any object exposing the same attrs).
        now: Current time (injected for deterministic tests).

    Returns:
        A :class:`SourceSummary`. A provider can be both active and expiring
        (enabled, nearly up) or active and expired (enabled, past its date —
        providers often keep serving). A disabled provider with no live
        subscription concern appears in none.
    """
    from metatv.gui.subscription_status import subscription_color

    active = expiring = expired = 0
    for p in providers:
        is_expired = bool(p.account_exp_date and p.account_exp_date <= now)
        color = (
            # ``now`` threaded through: this function takes one, and a
            # classification that honoured it for `is_expired` while
            # subscription_color reached for the real clock is not deterministic
            # at all — it just looked it.
            subscription_color(p.account_exp_date, p.account_created_at, now)
            if p.account_exp_date else ""
        )
        running_low = not is_expired and color in (_theme.COLOR_WARN, _theme.COLOR_ERR)
        # INDEPENDENT counts, not exclusive branches. "Active" answers "is this
        # source enabled and serving?"; "expiring" answers "is its subscription
        # running out?" — orthogonal questions about the same row. Counting
        # them with elif meant an enabled source with a lapsing subscription
        # was counted ONLY as expiring, so an install with two working sources
        # that both happened to be near renewal reported "0 active" and, once
        # the strip started leading with its most urgent fact, "No active
        # sources" — an outright false alarm about an app that was working.
        if p.is_active:
            active += 1
            if is_expired:
                expired += 1
        if running_low:
            expiring += 1
    return SourceSummary(active, expiring, expired)


def _summary_text(summary: SourceSummary, total: int) -> str:
    """The ONE thing worth saying about your sources right now.

    Every other section header follows the rule ``make_status_label`` states —
    news OR a count, never both, because a header showing "1 new · 13" is
    inventory with a decoration on it. This footer said up to four things at
    once ("Sources ● 0 active · ⚠ 2 expiring ⟳"), so it now follows the same
    rule: the most urgent fact wins and the rest is one click away in the
    manager.

    The ladder, worst first:

    * **no sources at all** — nothing to show, nothing works;
    * **none active** — you have sources and the app still has nothing to
      show, which is an alarm rather than inventory;
    * **some expired** — an enabled source is past its date (it may still
      serve, but renewal is overdue);
    * **some expiring** — a warning, actionable but not yet broken;
    * otherwise the plain count, quiet.

    Never colour alone: each rung carries its own words, and the warning rungs
    keep their glyph.
    """
    if total == 0:
        return "No sources yet"
    if summary.active == 0:
        return f"{_icon_utils.role_html('warning')} No active sources"
    if summary.expired:
        return f"{_icon_utils.role_html('warning')} {summary.expired} expired"
    if summary.expiring:
        return f"{_icon_utils.role_html('warning')} {summary.expiring} expiring"
    return f"{_icon_utils.role_html('status_dot')} {summary.active} active"


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
        _theme.style(self, "SOURCES_STRIP")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("Open the Sources manager")
        cursor_affordance.set_clickable(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 8, 7)
        layout.setSpacing(6)

        title = QLabel(f"{_icon_utils.role_html('provider')} Sources")
        title.setTextFormat(Qt.TextFormat.RichText)
        _theme.style(title, "SOURCES_STRIP_TITLE")
        layout.addWidget(title)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setTextFormat(Qt.TextFormat.RichText)   # carries an inline icon
        _theme.style(self._summary_lbl, "CHANNEL_NAME_DIM")
        layout.addWidget(self._summary_lbl, 1)

        self._refresh_btn = _icon_utils.icon_button(
            "refresh", "Refresh all sources", style="RECIPE_SAVED_ICON_BTN"
        )
        self._refresh_btn.setFixedSize(22, 20)
        self._refresh_btn.setFlat(True)
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
            summary = summarize_providers(providers, now)
            total = len(providers)
        self._summary_lbl.setText(_summary_text(summary, total))

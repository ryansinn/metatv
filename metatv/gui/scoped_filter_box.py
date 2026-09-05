"""ScopedFilterBox — the one search/filter line edit, wired for every surface.

SEARCH-10. Before this, a dozen views hand-rolled the same shape: a
``QLineEdit`` plus its own clear-button call, its own (often absent) debounce
``QTimer``, and its own Escape wiring — with results ranging from an unstyled
default box to a bespoke stylesheet. The text-match predicate and the global
search ladder were already single chokepoints; the WIDGET layer was not.
Owner: "shouldn't there be a single search mechanism that plugs into
different content?"

One widget now, adopted at every site that census found:

    1.  gui/sidebar/queue.py               "Find in queue…"          (debounce 0)
    2.  gui/epg_browse_mixin.py             "Search programmes…"      (debounce 0)
    3.  gui/epg_on_now_mixin.py             "Search On Now…"          (debounce 0)
    4.  gui/discover_view.py                "Filter shelves…"         (debounce 0)
    5.  gui/discover_browse.py              "Filter…"                 (debounce 0)
    6.  gui/filter_chip_bar.py              "Filter these results…"   (debounce 0)
    7.  gui/weighted_tag_cloud.py           "Filter…"                 (debounce 0)
    8.  gui/recipe_widgets.py               "Search tags across all facets…" (220ms)
    9.  gui/log_viewer_window.py            "Filter…"                 (debounce 0)
    10. gui/global_filter_dialog.py         "Search exclusions…"      (debounce 0)
    11. gui/app_header.py                  "Search titles…"           (debounce 0;
        keeps its own external debounce in main_window_channels.py — the
        ladder/wiring there is untouched, this box just replaces the plain
        QLineEdit it used to be)

Each site keeps its OWN placeholder text and its OWN debounce interval — those
are per-surface policy (how noisy is the underlying query, how large is the
result set), never duplication. What is shared is the shape: a clear button,
Escape-to-clear, and one theming role (``theme.SCOPED_FILTER_BOX``).

``tests/test_scoped_filter_box_is_the_one_search_input.py`` is the drift guard:
an AST walk fails the suite on any new hand-rolled ``QLineEdit`` construction
placeholdered "Search"/"Filter"/"Find", so the next one gets caught here
rather than found by grep in six months.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QLineEdit, QWidget

from metatv.gui import theme as _theme


class ScopedFilterBox(QLineEdit):
    """A ``QLineEdit`` that narrows a scoped view of content.

    Signals:
        filterChanged(str): the stripped filter text, emitted after
            ``debounce_ms`` of quiet typing (synchronously, on every
            keystroke, when ``debounce_ms`` is 0) — and immediately,
            bypassing any pending debounce, the moment the text becomes
            empty (clear button, Escape, or a programmatic ``clear()``).
        filterCleared(): emitted alongside ``filterChanged("")`` at that same
            moment — a cheap no-arg hook for a site that only cares THAT it
            was cleared (e.g. to fold itself away), without also having to
            filter on an empty string.
        escaped(): emitted on every Escape press (after clearing any text) —
            lets a host hide/collapse the box itself, e.g. the Watch Queue's
            find-in-queue panel, which hides on Escape whether or not there
            was text. The key event is consumed only when there WAS text to
            clear; Escape on an already-empty box propagates to the base
            implementation (and from there, up the widget tree) so a dialog
            hosting the box still closes on it.
    """

    filterChanged = pyqtSignal(str)
    filterCleared = pyqtSignal()
    escaped = pyqtSignal()

    def __init__(
        self,
        placeholder: str,
        *,
        debounce_ms: int = 150,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        _theme.style(self, "SCOPED_FILTER_BOX")

        self._debounce_ms = debounce_ms
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._emit_filter_changed)

        self.textChanged.connect(self._on_text_changed)

    # ── public ────────────────────────────────────────────────────────────

    def set_debounce_ms(self, debounce_ms: int) -> None:
        """Change the coalescing interval — e.g. wider for a heavier query."""
        self._debounce_ms = debounce_ms

    def current_filter(self) -> str:
        """The live, stripped filter text — independent of debounce timing."""
        return self.text().strip()

    # ── Qt overrides ─────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            had_text = bool(self.text())
            if had_text:
                self.clear()  # → _on_text_changed("") fires filterCleared + filterChanged("")
            # ``escaped`` fires either way: the Watch Queue hides its find box
            # on Escape whether or not there was text (the pre-SEARCH-10
            # QShortcut did), and a host that only cares about the clear can
            # ignore it. Only a consumed clear stops the key here — an
            # already-empty box lets Escape propagate (a dialog still closes).
            self.escaped.emit()
            if had_text:
                event.accept()
                return
        super().keyPressEvent(event)

    # ── private ──────────────────────────────────────────────────────────

    def _on_text_changed(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            # Nothing to coalesce when clearing — a debounced "restore
            # everything" reads as the app hanging for the interval.
            self._debounce.stop()
            self.filterCleared.emit()
            self.filterChanged.emit("")
            return
        if self._debounce_ms <= 0:
            self.filterChanged.emit(stripped)
        else:
            self._debounce.start(self._debounce_ms)

    def _emit_filter_changed(self) -> None:
        self.filterChanged.emit(self.text().strip())

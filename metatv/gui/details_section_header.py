"""One collapsible section header, instead of four copies and two absences.

The details pane had **four** hand-rolled collapsible sections — Technical,
Cast, Tags and Similar Titles — each with its own toggle button, its own
chevron flip, its own tooltip, its own `_collapsed` flag and its own
`restore_collapse_state`/`save_state` pair. It also had **two** sections that
could not collapse at all, Overview and Also-available, because collapsing one
meant writing a fifth copy.

Four copies is why they had drifted: two read their glyphs from `config`, one
from `icons`, and none of them could show a count beside the title, which the
V3 render asks for on Cast (`18`), Also-available (`65 versions · 19 regions`)
and Similar Titles.

So there is one header. A section gives it a title and a persistence key; it
gets the chevron, the click target, the remembered state and an optional
right-aligned summary — and adding a seventh section costs a constructor call
rather than a fifth copy of the same forty lines.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from metatv.gui import cursor_affordance
from metatv.gui import deferred_config_save as _cfgsave
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class CollapsibleHeader(QWidget):
    """`⌄ Title ............ summary` — the whole row is the click target.

    The title is a flat ``QPushButton`` rather than a label so the words are
    clickable too, not just the 20px chevron. Q21 settled that a section header
    toggles and never navigates, which is what makes widening the target safe.

    Signals:
        toggled: Emitted after the state flips. Carries the new *collapsed*.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, *, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed

        row = QHBoxLayout(self)
        row.setContentsMargins(0, _theme.space_px(_theme.SPACE_XS),
                               0, _theme.space_px(_theme.SPACE_XS))
        row.setSpacing(_theme.space_px(_theme.SPACE_XS))

        self._chevron = QPushButton()
        self._chevron.setFixedSize(20, 20)
        self._chevron.setFlat(True)
        _theme.style(self._chevron, "DETAIL_SECTION_CHEVRON")
        cursor_affordance.set_clickable(self._chevron)
        self._chevron.clicked.connect(self.toggle)
        row.addWidget(self._chevron)

        self._title = QPushButton(title)
        self._title.setFlat(True)
        _theme.style(self._title, "DETAIL_SECTION_TITLE")
        cursor_affordance.set_clickable(self._title)
        self._title.clicked.connect(self.toggle)
        row.addWidget(self._title)

        row.addStretch()

        # Right-aligned summary — "18", "65 versions · 19 regions". Hidden when
        # empty rather than left as a blank: an empty slot on some headers and
        # not others reads as a missing value.
        self._summary = QLabel()
        _theme.style(self._summary, "DETAIL_SECTION_SUMMARY")
        self._summary.hide()
        row.addWidget(self._summary)

        # Trailing controls (Similar Titles' ⤢). Added by the owning section.
        self._trailing = QHBoxLayout()
        self._trailing.setContentsMargins(0, 0, 0, 0)
        self._trailing.setSpacing(_theme.space_px(_theme.SPACE_XS))
        row.addLayout(self._trailing)

        self._sync()

    # ── State ────────────────────────────────────────────────────────────────

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Set the state without emitting — for restoring from config."""
        self._collapsed = bool(collapsed)
        self._sync()

    def toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._sync()
        self.toggled.emit(self._collapsed)

    def _sync(self) -> None:
        self._chevron.setText(
            _icons.expand_icon if self._collapsed else _icons.collapse_icon
        )
        # Set here, not at construction: the glyph flips with the state, so a
        # fixed tooltip would contradict the arrow half the time.
        hint = "Expand this section" if self._collapsed else "Collapse this section"
        self._chevron.setToolTip(hint)
        self._title.setToolTip(hint)

    # ── Content ──────────────────────────────────────────────────────────────

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def title(self) -> str:
        return self._title.text()

    def set_summary(self, summary: str, tooltip: str = "") -> None:
        """The right-aligned count. Empty string hides it."""
        self._summary.setText(summary)
        self._summary.setToolTip(tooltip)
        self._summary.setVisible(bool(summary))

    def summary(self) -> str:
        return self._summary.text()

    def add_trailing(self, widget: QWidget) -> None:
        """Add a control after the summary — Similar Titles' expand arrow."""
        self._trailing.addWidget(widget)


class CollapsibleMixin:
    """Wiring for a section that owns a :class:`CollapsibleHeader`.

    Expects ``self._header`` and ``self._content``, and a class-level
    ``COLLAPSE_KEY`` naming the section in
    ``config.details_pane_collapsed_sections``. That list is the existing
    persistence format and is deliberately unchanged — the four sections that
    already stored a key keep storing the same one, so nobody's remembered
    layout resets on upgrade.
    """

    COLLAPSE_KEY: str = ""

    def _wire_header(self) -> None:
        self._header.toggled.connect(self._on_header_toggled)
        self._apply_collapsed()

    def _on_header_toggled(self, _collapsed: bool) -> None:
        self._apply_collapsed()

    def _apply_collapsed(self) -> None:
        self._content.setVisible(not self._header.is_collapsed())

    def restore_collapse_state(self, collapsed_sections) -> None:
        self._header.set_collapsed(self.COLLAPSE_KEY in (collapsed_sections or []))
        self._apply_collapsed()

    def save_state(self, host) -> None:
        """Persist this section's state into the shared list.

        Args:
            host: The details-pane object owning ``config`` — passed (not the
                bare ``Config``) so the write can settle through
                ``deferred_config_save.save_soon`` instead of writing on
                every collapse/expand click.
        """
        config = host.config
        sections = list(getattr(config, "details_pane_collapsed_sections", []) or [])
        if self._header.is_collapsed():
            if self.COLLAPSE_KEY not in sections:
                sections.append(self.COLLAPSE_KEY)
        elif self.COLLAPSE_KEY in sections:
            sections.remove(self.COLLAPSE_KEY)
        config.details_pane_collapsed_sections = sections
        _cfgsave.save_soon(host)

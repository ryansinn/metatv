"""Modal shown after a source refresh/import surfaces NEW filter facet values.

The filter panel follows an opt-out model (docs/FILTERING_DESIGN.md): content is
visible by default, so a facet value that appears for the first time — e.g. a
region code a freshly-imported source introduced — is INCLUDED automatically.
This dialog tells the user which values are new and lets them opt specific ones
out.  Everything is checked by default; on confirm the unchecked values are
excluded from the filter selection, on cancel they all stay included.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class NewFacetValuesDialog(QDialog):
    """List newly-seen facet values grouped by facet; opt-out on confirm.

    Args:
        new_values: ``{section_key: set(value)}`` — the new values per facet.
        titles: ``{section_key: display_title}`` (e.g. ``"region" → "Region"``).
            Iteration order of this mapping drives the section order in the dialog.
        labels: optional ``{section_key: {value: label}}`` display-label override
            (used for Region ISO codes → full names).  Missing values fall back to
            the raw value string.
        parent: optional Qt parent.
    """

    def __init__(
        self,
        new_values: dict[str, set[str]],
        titles: dict[str, str],
        labels: dict[str, dict[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._checks: dict[str, dict[str, QCheckBox]] = {}
        labels = labels or {}

        self.setWindowTitle("New Filter Values")
        self.setMinimumWidth(360)

        vl = QVBoxLayout(self)
        vl.setSpacing(10)

        header = QLabel(f"{_icons.discover_icon} New filter values found")
        header.setStyleSheet(
            f"font-size: {_theme.FONT_XL}; font-weight: bold; color: {_theme.COLOR_TEXT_2};"
        )
        vl.addWidget(header)

        hint = QLabel(
            "A source refresh introduced values that weren't in your filters "
            "before. They're included by default so nothing gets hidden — "
            "uncheck any you'd like to exclude."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_MUTED};")
        vl.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(2, 2, 2, 2)
        il.setSpacing(2)

        for section_key, title in titles.items():
            values = new_values.get(section_key)
            if not values:
                continue
            grp_lbl = QLabel(title.upper())
            grp_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_SM}; font-weight: bold; "
                f"color: {_theme.COLOR_MUTED_2}; letter-spacing: 1px; padding-top: 6px;"
            )
            il.addWidget(grp_lbl)

            value_labels = labels.get(section_key, {})
            self._checks[section_key] = {}
            for value in sorted(values, key=lambda v: value_labels.get(v, v).lower()):
                display = value_labels.get(value, value)
                if display != value:
                    display = f"{display}  ({value})"
                cb = QCheckBox(display)
                cb.setChecked(True)
                cb.setStyleSheet(
                    f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_TEXT};"
                )
                il.addWidget(cb)
                self._checks[section_key][value] = cb

        il.addStretch()
        scroll.setWidget(inner)
        vl.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Apply")
        ok_btn.setToolTip("Exclude the unchecked values; keep the rest included")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("Include all")
        cancel_btn.setToolTip("Keep every new value included")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vl.addWidget(buttons)

    def excluded(self) -> dict[str, set[str]]:
        """Return ``{section_key: set(unchecked values)}`` — the opt-out selections.

        Only meaningful after the dialog was accepted: the unchecked values should
        be removed from the corresponding filter section's selection (excluded).
        Facets with nothing unchecked are omitted.
        """
        result: dict[str, set[str]] = {}
        for section_key, checks in self._checks.items():
            unchecked = {v for v, cb in checks.items() if not cb.isChecked()}
            if unchecked:
                result[section_key] = unchecked
        return result

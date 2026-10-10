"""Settings → Appearance → Text size: one control, from choices to config.

Its own module so the settings tabs file (pinned at its size) gains one call,
not a block. The scale multiplies every ``FONT_*`` token through
``theme.set_text_scale`` — the theme stays the one owner of sizes.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QFormLayout

#: (label, multiplier on every FONT_* token).
TEXT_SIZE_CHOICES: tuple[tuple[str, float], ...] = (
    ("Smaller (90%)", 0.9),
    ("Default", 1.0),
    ("Larger (110%)", 1.1),
    ("Large (125%)", 1.25),
    ("Largest (150%)", 1.5),
)


def add_text_size_row(form: QFormLayout) -> QComboBox:
    """Add the "Text size:" row to *form* and return its combo."""
    combo = QComboBox()
    for label, value in TEXT_SIZE_CHOICES:
        combo.addItem(label, value)
    combo.setToolTip(
        "Scales all text in MetaTV — the same size on Linux and macOS,\n"
        "independent of the system font setting. Applies when you click\n"
        "OK or Apply.")
    form.addRow("Text size:", combo)
    return combo


def load_text_size(combo: QComboBox, config) -> None:
    """Select ``config.ui_text_scale`` in *combo* (nearest choice)."""
    scale = float(getattr(config, "ui_text_scale", 1.0) or 1.0)
    best = min(range(combo.count()), key=lambda i: abs(float(combo.itemData(i)) - scale),
               default=-1)
    combo.setCurrentIndex(best)


def save_text_size(combo: QComboBox, config) -> None:
    """Write the selected multiplier back to ``config.ui_text_scale``."""
    config.ui_text_scale = float(combo.currentData() or 1.0)

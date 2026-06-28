"""Behavioral tests for the FILTERED VARIANTS collapsible section in _VersionSection.

Covers three QC-rejected bugs from PR #234:
  - Bug 1: chips don't populate when the section is expanded
  - Bug 2: header label is not clickable (only chevron was)
  - Bug 3: the header appears when there are zero filtered variants

Headless-safe: uses isHidden() (explicit hide state) not isVisible() (ancestor-gated).
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def _active_version(channel_id: str = "a1") -> "ChannelVersion":
    from metatv.gui.details_versions import ChannelVersion
    return ChannelVersion(channel_id=channel_id, name="Active", in_queue=False,
                          detected_prefix="US", is_filtered=False)


def _filtered_version(channel_id: str = "f1") -> "ChannelVersion":
    from metatv.gui.details_versions import ChannelVersion
    return ChannelVersion(channel_id=channel_id, name="Filtered", in_queue=False,
                          detected_prefix="UK", is_filtered=True)


# ---------------------------------------------------------------------------
# Bug 1: chips populate after expand
# ---------------------------------------------------------------------------

def test_filtered_chips_are_added_to_layout_after_load(qapp):
    """load() with filtered variants must add chips to _filtered_chips_layout."""
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection(_make_config())
    section.load([_active_version(), _filtered_version()])

    assert section._filtered_chips_layout.count() == 1, (
        "One filtered variant should produce one chip in _filtered_chips_layout"
    )


def test_filtered_chips_not_hidden_after_toggle(qapp):
    """After load() with filtered variants, expanding the section makes chips non-hidden.

    Uses isHidden() (explicit hide) — not isVisible() (ancestor-gated) — so the test
    passes even in a headless environment where the top-level widget is never shown.
    """
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection(_make_config())
    section.load([_active_version(), _filtered_version("f2")])

    # Confirm section is initially collapsed
    assert section._filtered_chips_row.isHidden(), (
        "_filtered_chips_row must start collapsed (hidden) after load()"
    )

    section._toggle_filtered_section()

    assert not section._filtered_chips_row.isHidden(), (
        "After toggle, _filtered_chips_row must not be explicitly hidden"
    )
    # Every chip in the layout must also be non-hidden
    for i in range(section._filtered_chips_layout.count()):
        item = section._filtered_chips_layout.itemAt(i)
        if item and item.widget():
            assert not item.widget().isHidden(), (
                f"Chip at index {i} must not be explicitly hidden after expand"
            )


def test_toggle_twice_re_collapses_chips(qapp):
    """Toggling twice restores the collapsed state."""
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection(_make_config())
    section.load([_active_version(), _filtered_version("f3")])

    section._toggle_filtered_section()  # expand
    section._toggle_filtered_section()  # collapse

    assert section._filtered_chips_row.isHidden(), (
        "After two toggles, _filtered_chips_row must be hidden again (collapsed)"
    )


# ---------------------------------------------------------------------------
# Bug 2: header label is clickable
# ---------------------------------------------------------------------------

def test_header_label_is_a_button(qapp):
    """_filtered_hdr_lbl must be a QPushButton so it can receive click events."""
    from PyQt6.QtWidgets import QPushButton
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection(_make_config())
    assert isinstance(section._filtered_hdr_lbl, QPushButton), (
        "_filtered_hdr_lbl must be a QPushButton, not a QLabel, so it is clickable"
    )


def test_clicking_header_label_toggles_section(qapp):
    """Clicking _filtered_hdr_lbl (the text label) must expand/collapse the chips row."""
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection(_make_config())
    section.load([_active_version(), _filtered_version("f4")])

    assert section._filtered_chips_row.isHidden(), "Must start collapsed"

    # Click the TEXT LABEL (not the chevron button)
    section._filtered_hdr_lbl.click()

    assert not section._filtered_chips_row.isHidden(), (
        "Clicking the header label must expand the chips row"
    )

    # Click again — must collapse
    section._filtered_hdr_lbl.click()

    assert section._filtered_chips_row.isHidden(), (
        "Clicking the header label a second time must collapse the chips row"
    )


# ---------------------------------------------------------------------------
# Bug 3: header hidden when zero filtered variants
# ---------------------------------------------------------------------------

def test_filtered_section_hidden_when_no_filtered_variants(qapp):
    """load() with zero filtered variants must leave _filtered_section hidden."""
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection(_make_config())
    section.load([_active_version()])  # only active, no filtered

    assert section._filtered_section.isHidden(), (
        "_filtered_section must be hidden when there are no filtered variants"
    )


def test_filtered_section_hidden_on_reload_from_some_to_zero_filtered(qapp):
    """A reload from some-filtered to zero-filtered must hide _filtered_section."""
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection(_make_config())

    # First load: one filtered variant → section should appear
    section.load([_active_version(), _filtered_version("f5")])
    assert not section._filtered_section.isHidden(), (
        "First load with a filtered variant must show _filtered_section"
    )

    # Reload with only active variants → section must disappear
    section.load([_active_version("a2")])
    assert section._filtered_section.isHidden(), (
        "After reload with zero filtered variants, _filtered_section must be hidden"
    )


def test_filtered_section_hidden_when_versions_empty(qapp):
    """load([]) (clear) must hide _filtered_section even if it was previously visible."""
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection(_make_config())
    section.load([_active_version(), _filtered_version("f6")])
    section.load([])  # clear

    assert section._filtered_section.isHidden(), (
        "_filtered_section must be hidden after load([])"
    )

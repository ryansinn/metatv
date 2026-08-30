"""The transparency bar is a table of axes, not five hand-written copies.

Adding an axis used to mean editing nine sites across two files — the
measurement, the params publish, the reads, the ``elif``, the render signature,
its booleans, its body, its ``or``-chain, and a button-name tuple in
``refresh_theme``. Every one was a place an axis could be forgotten, and one
was: the adult-content gate was an axis nobody had added, so a category whose
28 channels are all flagged rendered 0 rows under "try a different search".
Ledger F26.

These tests hold the two properties that make the table worth having: the data
is COMPLETE (no axis can be half-registered) and the rendered strings are
UNCHANGED by the extraction.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from metatv.gui import channel_transparency as ct


# --------------------------------------------------------------------------- #
# The table is complete — no axis can be half-registered.
# --------------------------------------------------------------------------- #

def test_every_axis_names_a_handler_that_exists():
    """A typo'd handler name would crash at window construction, not here.

    The handler is stored as a NAME because the table is built at import time,
    before any window exists — so nothing checks it until a real window wires
    the bar. This does.
    """
    from metatv.gui.main_window import MainWindow

    missing = [a.handler for a in ct.AXES if not hasattr(MainWindow, a.handler)]
    assert not missing, f"axes point at handlers MainWindow does not have: {missing}"


def test_every_axis_is_fully_populated():
    """An axis missing a field renders a blank button or an unlabelled one."""
    for axis in ct.AXES:
        assert axis.key, "axis has no key"
        assert axis.attr.startswith("_channel_"), f"{axis.key}: odd attr {axis.attr}"
        assert axis.icon, f"{axis.key}: no icon"
        assert axis.suffix, f"{axis.key}: no suffix — the button would be a bare count"
        assert axis.tooltip, f"{axis.key}: no tooltip"


def test_axis_keys_and_attrs_are_unique():
    """Two axes sharing a key would silently overwrite each other's count."""
    keys = [a.key for a in ct.AXES]
    attrs = [a.attr for a in ct.AXES]
    assert len(set(keys)) == len(keys), f"duplicate axis key in {keys}"
    assert len(set(attrs)) == len(attrs), f"duplicate button attr in {attrs}"


def test_button_attrs_covers_every_axis():
    """``refresh_theme`` iterates BUTTON_ATTRS; a gap means an unstyled segment."""
    assert set(ct.BUTTON_ATTRS) == {a.attr for a in ct.AXES}


def test_every_icon_comes_from_the_icons_module():
    """No glyph literals in the table — icons.py is the one source (CLAUDE.md)."""
    from metatv.gui import icons

    registered = {
        v for k, v in vars(icons).items()
        if isinstance(v, str) and k.endswith("_icon")
    }
    for axis in ct.AXES:
        assert axis.icon in registered, (
            f"{axis.key}'s icon {axis.icon!r} is not registered in icons.py"
        )


# --------------------------------------------------------------------------- #
# The extraction changed no rendered text.
# --------------------------------------------------------------------------- #

#: The exact text each segment renders. The first four were transcribed from the
#: hand-written blocks that existed BEFORE the extraction — a refactor that
#: reworded the UI would be a behaviour change wearing a refactor's clothes.
#:
#: The parametrised test below covers every axis in AXES, so a new one fails
#: here with a KeyError until its rendered string is written down. That is the
#: guard working: the adult gate arrived this way.
_EXPECTED = {
    "exclusions": "🔒 4 hidden by Global Exclusions  —  show",
    "search":     "🔎 4 hidden by search filters  —  show",
    "dead":       "⚠ 4 unavailable (repeated play failures)  —  show",
    "keywords":   "🔤 4 hidden by keywords  —  show",
    "adult":      "🔞 4 hidden as adult content  —  change in Settings",
}


class _Host:
    """A bare stand-in — render() must not need a real MainWindow."""

    def __init__(self, qapp):
        self._channel_filter_bar = QWidget()
        for axis in ct.AXES:
            setattr(self, axis.attr, QPushButton())


@pytest.mark.parametrize("axis", ct.AXES, ids=lambda a: a.key)
def test_each_segment_renders_its_expected_text(qapp, axis):
    host = _Host(qapp)
    ct.render(host, counts={axis.key: 4}, floors={})
    assert getattr(host, axis.attr).text() == _EXPECTED[axis.key], (
        f"{axis.key} renders {getattr(host, axis.attr).text()!r}"
    )


def test_a_floor_count_is_marked_as_one(qapp):
    host = _Host(qapp)
    ct.render(host, counts={"dead": 5000}, floors={"dead": True})
    text = host._channel_dead_btn.text()
    assert "≥ 5,000" in text, f"floor not marked in {text!r}"


def test_only_the_axes_with_counts_are_shown(qapp):
    host = _Host(qapp)
    ct.render(host, counts={"search": 7}, floors={})
    assert host._channel_filter_btn.isVisible()
    assert not host._channel_exclusion_btn.isVisible()
    assert host._channel_filter_bar.isVisible()


def test_the_bar_hides_when_nothing_is_hidden(qapp):
    host = _Host(qapp)
    ct.render(host, counts={}, floors={})
    assert not host._channel_filter_bar.isVisible()
    for axis in ct.AXES:
        assert not getattr(host, axis.attr).isVisible()


def test_render_tolerates_a_host_missing_buttons(qapp):
    """A skeleton test host wires some buttons, not all — that must not raise."""
    host = _Host(qapp)
    del host.__dict__[ct.AXES[0].attr]
    ct.render(host, counts={a.key: 1 for a in ct.AXES}, floors={})
    assert host._channel_filter_bar.isVisible()


def test_render_is_a_no_op_without_a_bar(qapp):
    """Before setup_ui builds the bar, rendering must do nothing rather than raise."""
    class _Bare:
        pass

    ct.render(_Bare(), counts={"dead": 3}, floors={})


# --------------------------------------------------------------------------- #
# Construction wires every segment.
# --------------------------------------------------------------------------- #

def test_build_segments_creates_and_connects_every_axis(qapp):
    host = _Host(qapp)
    fired = []
    for axis in ct.AXES:
        # `checked` first: QPushButton.click() passes it, and it would
        # otherwise bind to the key default and record False for every axis.
        setattr(host, axis.handler,
                lambda checked=False, k=axis.key: fired.append(k))

    container = QWidget()
    layout = QHBoxLayout(container)
    ct.build_segments(host, layout, "QPushButton { color: red; }")

    assert layout.count() == len(ct.AXES), "a segment was not added to the bar"
    for axis in ct.AXES:
        button = getattr(host, axis.attr)
        assert button.toolTip() == axis.tooltip
        assert not button.isVisible(), "segments start hidden"
        button.click()

    assert fired == [a.key for a in ct.AXES], (
        f"segments are wired to the wrong handlers: {fired}"
    )

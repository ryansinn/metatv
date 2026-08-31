"""There is one flow layout per contract, and both live in ``flow_layout.py``.

The componentization audit ("The Discoverable Wrong Path") found FOUR copies of
this primitive with THREE visibility policies between them:

- ``flow_layout.FlowLayout`` — the packaged one, and the one nobody reached for.
  Laid out hidden children unconditionally, leaving a hole where a hidden chip
  sat.
- ``details_versions._FlowLayout`` — the de-facto standard with SEVEN call
  sites, and strictly better: separate h/v spacing plus an ``isHidden()`` skip
  carrying its own bug-fix rationale.
- ``weighted_tag_cloud._FlowLayout`` — whose docstring confessed the copy:
  *"the same layout primitive used by ``discover_card._FlowLayout`` … We define
  our own copy here rather than importing the private class from
  ``discover_card`` so this widget has no coupling to the Discover subsystem."*
  Avoiding that coupling was right; a shared module is how you get it.
- ``discover_card._FlowLayout`` — the one it was copied FROM, and by then dead:
  zero instantiations anywhere in the tree.

Two remain because two contracts genuinely differ. ``FlowLayout`` is a
``QLayout``: Qt drives it and the host never asks how tall the result was.
``FlowContainer`` is driven by the host, which passes a width and needs the
height BACK to size a scroll area. That is a policy difference, not a
duplicate — and calling a policy difference a duplicate is how a silent
behaviour change ships.
"""

from __future__ import annotations

import ast
import pathlib

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QLabel, QWidget

from metatv.gui.flow_layout import FlowContainer, FlowLayout


_GUI = pathlib.Path(__file__).resolve().parent.parent / "metatv" / "gui"
_HOME = "flow_layout.py"


def test_no_module_defines_its_own_flow_layout():
    """AST-based, so the prose above — which names every copy — cannot trip it."""
    offenders = []
    for path in sorted(_GUI.rglob("*.py")):
        if path.name == _HOME:
            continue
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "flowlayout" in node.name.lower().replace("_", ""):
                offenders.append(f"{path.name}:{node.lineno} defines {node.name}")
            if isinstance(node, ast.ClassDef) and "flowcontainer" in node.name.lower().replace("_", ""):
                offenders.append(f"{path.name}:{node.lineno} defines {node.name}")
    assert not offenders, (
        "a flow layout defined outside flow_layout.py: " + "; ".join(offenders)
        + ". Import FlowLayout (a QLayout) or FlowContainer (host-driven, "
        "returns its height) instead of copying one."
    )


def test_both_contracts_are_exported_from_the_one_home():
    from metatv.gui import flow_layout
    assert hasattr(flow_layout, "FlowLayout")
    assert hasattr(flow_layout, "FlowContainer")


# ── the visibility policy, which is what actually differed ──────────────────

def _chips(layout_or_container, n=4, w=50, h=20):
    host = QWidget()
    host.resize(130, 400)
    widgets = []
    for i in range(n):
        label = QLabel(str(i))
        label.setFixedSize(w, h)
        widgets.append(label)
    return host, widgets


def test_a_hidden_chip_leaves_no_gap_between_its_neighbours(qapp):
    """The bug the packaged layout carried, asserted on PAINTED POSITIONS.

    Height alone cannot see this: Qt already reports ``QSize(0, 0)`` for a
    hidden widget, so the row height changes either way. What the skip removes
    is the residual SPACING the zero-width item still advances past — measured
    at exactly one spacing unit, which is a visible gap in a chip row.

    With the skip:    x = [11, 71, 131]
    Without it:       x = [11, 81, 141]   <- 10px hole where chip 1 sat
    """
    host = QWidget()
    host.resize(400, 400)
    layout = FlowLayout(host, spacing=10)
    chips = []
    for i in range(4):
        label = QLabel(str(i))
        label.setFixedSize(50, 20)
        layout.addWidget(label)
        chips.append(label)

    chips[1].hide()
    layout.setGeometry(QRect(0, 0, 400, 400))
    xs = [c.geometry().x() for i, c in enumerate(chips) if i != 1]

    gaps = [b - a for a, b in zip(xs, xs[1:])]
    assert gaps, "expected at least two visible chips to compare"
    assert all(g == 60 for g in gaps), (
        f"visible chips sit at {xs}; a hidden neighbour must not push them along. "
        "Each gap should be chip width (50) + spacing (10) = 60; a larger gap is "
        "the hole a hidden item leaves when it is laid out instead of skipped."
    )


def test_a_never_shown_chip_is_still_laid_out(qapp):
    """The opposite error, and the reason the predicate is isHidden().

    ``isVisible()`` is False for every widget whose window has not been shown —
    which is all of them under a headless runner, and all of them inside a
    COLLAPSED container. Skipping those makes heightForWidth return 0 and the
    row renders with no height after expansion.
    """
    host, chips = _chips(None)
    layout = FlowLayout(host, spacing=10)
    for c in chips:
        layout.addWidget(c)
    assert not chips[0].isVisible(), "precondition: nothing has been shown"
    assert not chips[0].isHidden(), "precondition: nothing was explicitly hidden"
    assert layout.heightForWidth(130) > 0, "an unshown chip must still occupy space"


def test_horizontal_and_vertical_spacing_are_separable(qapp):
    """A chip row wants tighter rows than columns; one `spacing` cannot say that."""
    host_a, chips_a = _chips(None)
    wide = FlowLayout(host_a, spacing=10)
    for c in chips_a:
        wide.addWidget(c)

    host_b, chips_b = _chips(None)
    tight = FlowLayout(host_b, h_spacing=10, v_spacing=4)
    for c in chips_b:
        tight.addWidget(c)

    assert tight.heightForWidth(130) < wide.heightForWidth(130)


def test_the_container_reports_its_height_and_zero_when_empty(qapp):
    """The contract that makes FlowContainer a sibling rather than a duplicate."""
    host = QWidget()
    container = FlowContainer(host, spacing=10)
    assert container.relayout(130) == 0, "an empty flow occupies nothing"
    for i in range(4):
        label = QLabel(str(i))
        label.setFixedSize(50, 20)
        container.add(label)
    two_rows = container.relayout(130)
    assert two_rows > 20, "four 50px chips in 130px must wrap to two rows"


def test_the_container_honours_a_caller_supplied_predicate(qapp):
    """The tag cloud's buttons carry their own filtered state.

    That is not the same question as Qt visibility, so it is passed in rather
    than renamed into the shared default.
    """
    host = QWidget()
    container = FlowContainer(
        host, spacing=10, is_visible=lambda w: getattr(w, "cloud_visible", True))
    chips = []
    for i in range(4):
        label = QLabel(str(i))
        label.setFixedSize(50, 20)
        label.cloud_visible = True
        container.add(label)
        chips.append(label)
    full = container.relayout(130)
    chips[0].cloud_visible = False
    chips[1].cloud_visible = False
    assert container.relayout(130) < full

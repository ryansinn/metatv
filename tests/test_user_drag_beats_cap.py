"""A section the user drags taller stays taller.

The content cap exists so the splitter never hands a section room it cannot
fill — "recommended should never really be able to go beyond the length of the
list ... otherwise it's just dead space". That is a rule for AUTOMATIC
allocation.

It was applied as a real ``setMaximumHeight``, which also overrules a person.
On a sparse library the effect is total: with little content every section caps
just above its header, so dragging a handle updates ``QSplitter.sizes()`` while
the widgets stay exactly where they were. Measured headless before the fix — a
splitter reporting ``[298, 298]`` around two sections both pinned at 108px, with
~190px each of allocation nothing honoured. Owner: "the vertical resize doesn't
work ... the icon changes, but the resize doesn't happen".

An earlier version of ``section_cap`` remembered the user's height and was
deleted because "none of that machinery could be shown to do anything" — every
test stayed green when it was mutated away. This file is the reproduction that
was missing.
"""

from __future__ import annotations


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter

from metatv.core.config import Config
from metatv.gui.sidebar.favorites import FavoritesSection
from metatv.gui.sidebar.history import HistorySection


def _build_stack(qapp, tmp_path):
    """Two EMPTY sections in a vertical splitter — the sparse-library shape.

    Built inside each test rather than yielded from a fixture: the sections
    settle their caps during the first event loop turn after show(), and a
    fixture that yields across that boundary hands the test a stack whose
    geometry has not converged, which reads as the fix not working.
    """
    cfg = Config(config_dir=tmp_path)
    sp = QSplitter(Qt.Orientation.Vertical)
    top, bottom = FavoritesSection(cfg, db=None), HistorySection(cfg, db=None)
    sp.addWidget(top)
    sp.addWidget(bottom)
    sp.resize(320, 600)
    sp.show()
    qapp.processEvents()
    return sp, top, bottom


def test_without_a_drag_the_content_cap_still_applies(qapp, tmp_path):
    """The owner's rule, preserved: automatic space is not dead space."""
    sp, top, _ = _build_stack(qapp, tmp_path)
    sp.setSizes([400, 200])
    qapp.processEvents()

    assert top.height() < 400, (
        "an empty section accepted 400px of automatic allocation and would pad "
        "the surplus around nothing"
    )
    assert top.maximumHeight() == top.max_useful_height()


def test_a_dragged_height_is_honoured(qapp, tmp_path):
    """The bug: the widget refused the height the splitter gave it."""
    sp, top, bottom = _build_stack(qapp, tmp_path)
    before = top.height()

    for section in (top, bottom):
        section.note_user_height(300)          # what splitterMoved reports
    sp.setSizes([300, 296])
    qapp.processEvents()

    assert top.height() > before, (
        f"the section did not grow: {before} -> {top.height()}"
    )
    assert top.height() >= 300 - 4, (
        f"dragged to 300 but settled at {top.height()} — the cap still wins"
    )


def test_the_cap_rises_to_the_user_height(qapp, tmp_path):
    sp, top, _ = _build_stack(qapp, tmp_path)
    content_cap = top.max_useful_height()
    top.note_user_height(320)
    assert top.max_useful_height() >= 320 > content_cap
    assert top.maximumHeight() >= 320


def test_a_drag_down_to_the_header_is_not_remembered(qapp, tmp_path):
    """Collapsing to the header is a collapse, not "I want this section small".

    Remembering it would pin the section at its floor forever, which is the
    mirror image of the bug being fixed.
    """
    sp, top, _ = _build_stack(qapp, tmp_path)
    floor = top.min_expanded_height()
    top.note_user_height(floor)
    assert top.__dict__.get("_user_height") in (None, 0), (
        "a drag to the floor was stored as a preferred height"
    )


def test_growing_content_still_raises_the_cap(qapp, tmp_path):
    """The user height is a FLOOR on the cap, never a ceiling on content."""
    sp, top, _ = _build_stack(qapp, tmp_path)
    top.note_user_height(200)
    assert top.max_useful_height() >= 200
    # A taller content measurement must still win if it exceeds the user height.
    #
    # DERIVED from the content, not a constant. This line read
    # ``top._user_height = 50`` and passed only because an empty section
    # measured 108px — ``viewportSizeHint()`` on an empty QListWidget returns a
    # default viewport rather than 0, and that fabricated 82px of content was
    # what kept 50 "small". Fixing the measurement (an empty section is now its
    # header) dropped the content under 50 and the assertion started failing on
    # a premise it never meant to state.
    content_cap = max(top.min_expanded_height(),
                      top.HEADER_H + top._content_height())
    top._user_height = max(0, content_cap - 1)
    assert top.max_useful_height() == content_cap, (
        "a stale user height SMALLER than the content must not cap it")

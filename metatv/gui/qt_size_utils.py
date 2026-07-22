"""Small, reusable Qt widget-sizing helpers shared across dialogs/panes.

Single chokepoint for the "word-wrapped QLabel forces its container the
wrong size" family of Qt layout traps documented in
docs/DETAILS_PANE_DESIGN.md → "Width discipline". Any new caller with a
``setWordWrap(True)`` label inside a ``QScrollArea`` should reach for
``no_width_force`` here rather than re-deriving the fix locally.
"""

from PyQt6.QtWidgets import QLabel, QSizePolicy


def no_width_force(label: QLabel) -> None:
    """Let a word-wrapped label wrap/break to the available width instead of
    forcing its container wider — or, for the same underlying reason,
    shorter than its text needs (clipping the tail).

    A wrapping ``QLabel`` reports ``minimumSizeHint().width()`` equal to its
    longest *unbreakable* word, because word-wrap only breaks at spaces.  A
    scene-release-style token (e.g.
    ``A.Very.Long.Release.Name.1998.1080p.BluRay.x265-GROUP``) or a URL has no
    spaces, so the label's minimum width becomes that whole token — and
    inside a width-resizable, horizontal-scrollbar-off ``QScrollArea`` that
    floors the *entire* content column at that width, clipping every other
    section off the right edge (see docs/DETAILS_PANE_DESIGN.md → "Width
    discipline", entry 123).

    Ignoring the horizontal hint lets the layout shrink the label to the
    container width; Qt then breaks the long token at a character boundary
    instead of widening the container.

    It also has a second, load-bearing effect on *height*: with the default
    ``Preferred`` horizontal policy, Qt's box-layout heightForWidth support
    pre-computes a wrapped label's height using the label's own wide,
    unconstrained preferred width (from ``sizeHint()``) — not the narrower
    width it will actually render at once squeezed into the scroll area's
    viewport. That under-computes the wrapped height and clips the tail of
    the text (see ``metatv/gui/whats_new_dialog.py`` for the entry-clipping
    bug this fixed — the same mismatch, hitting the height axis instead of
    width). ``Ignored`` sidesteps both.
    """
    sp = label.sizePolicy()
    sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    label.setSizePolicy(sp)

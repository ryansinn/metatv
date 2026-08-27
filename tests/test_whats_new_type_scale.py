"""The What's New card, measured as Qt renders it.

The dialog had three sizes fighting: its own "What's New" header at FONT_3XL,
an entry title at FONT_2XL immediately below it, and bullets at FONT_LG. The
entry title is a card heading inside a dialog, not a view title, and at 20px it
read as a second banner rather than as the name of the card it sits in. Owner:
"what's new content could be sized down slightly. same with the title of the
whats new entry (not the 'What's New' title)".

So both stepped down one place on the scale — title 2XL→XL, bullets LG→MD —
and the header did not move, because it is the one thing here that should be
the biggest text on screen.

Every assertion below is on the RENDERED font metrics of the dialog's real
labels, not on the token strings: `font-size` does not map 1:1 onto painted
height, and a role that merely *names* a smaller token can still land in the
same 1px band. Sibling of tests/test_type_scale_rendered.py, which holds the
scale itself.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel

from metatv.gui import theme
from metatv.gui.whats_new_dialog import WhatsNewDialog
from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=1,
    version="9.9.9",
    date="2026-08-26",
    title="Sidebar groups stay how you left them",
    items=("A bullet long enough to wrap at the dialog's width, which is how "
           "these actually render.",
           "A second bullet."),
    test_steps=("Open the dialog.",),
)


def _rendered_px(token: str) -> int:
    """Painted height of a bare label carrying *token*, for comparison."""
    probe = QLabel("Sample")
    probe.setStyleSheet(f"font-size: {token};")
    probe.ensurePolished()
    height = probe.fontMetrics().height()
    probe.deleteLater()
    return height


@pytest.fixture
def card_labels(qtbot):
    """The dialog's real header / title / meta / bullet labels, polished.

    Built through ``WhatsNewDialog`` rather than by applying the role to a bare
    label: the roles reach these widgets via ``theme.style()``, and Qt resolves
    a stylesheet to an effective font only on polish. A test that styles its own
    label proves the token, not the dialog.
    """
    dlg = WhatsNewDialog([ENTRY])
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    found: dict[str, QLabel] = {}
    bullets: list[QLabel] = []
    for label in dlg.findChildren(QLabel):
        label.ensurePolished()
        text = label.text()
        if text.endswith("What's New"):
            found["header"] = label
        elif text == ENTRY.title:
            found["title"] = label
        elif text.startswith(f"v{ENTRY.version}"):
            found["meta"] = label
        elif ENTRY.items[0] in text:
            bullets.append(label)
    assert {"header", "title", "meta"} <= found.keys(), sorted(found)
    assert bullets, "no bullet label found"
    found["item"] = bullets[0]
    return {k: v.fontMetrics().height() for k, v in found.items()}


def test_the_entry_title_no_longer_renders_as_a_second_banner(card_labels):
    """RED at FONT_2XL, which is where this started."""
    assert card_labels["title"] <= _rendered_px(theme.FONT_XL)
    assert card_labels["title"] < _rendered_px(theme.FONT_2XL), (
        f"the entry title paints {card_labels['title']}px — the same band as "
        "the FONT_2XL it was supposed to step down from"
    )


def test_the_bullets_render_at_body_size(card_labels):
    """RED at FONT_LG."""
    assert card_labels["item"] <= _rendered_px(theme.FONT_MD)
    assert card_labels["item"] < _rendered_px(theme.FONT_LG), (
        f"bullets paint {card_labels['item']}px, unchanged from FONT_LG"
    )


def test_the_bullets_still_clear_the_legibility_floor(card_labels):
    """The other half of "slightly" — this is the app's own body-text floor.

    Without it, "size it down" has no stopping point and the next nudge is
    unreadable rather than merely smaller.

    Measured against what body text paints ON THIS PLATFORM, not against a
    number. The first version asserted ``>= 17``, which is what FONT_MD paints
    on Linux — and macOS paints the same token at 16, so it failed CI while the
    bullets were exactly the size intended. The claim was never "17px"; it was
    "no smaller than body text", and that is what this now says.
    """
    body = _rendered_px(theme.FONT_MD)
    assert card_labels["item"] >= body, (
        f"bullets paint {card_labels['item']}px against body text's {body}px — "
        "they have gone below the size the rest of the app reads at"
    )


def test_the_dialog_header_is_the_biggest_thing_on_screen(card_labels):
    """Explicitly out of scope for the shrink, and now unambiguous.

    It was 24px over a 20px title — 1.2x, which reads as two headings rather
    than a heading and the card beneath it.
    """
    assert card_labels["header"] > card_labels["title"]
    assert card_labels["header"] / card_labels["title"] >= 1.15, (
        f"header {card_labels['header']}px vs title {card_labels['title']}px"
    )


def test_the_card_reads_top_to_bottom(card_labels):
    """Title, then bullets, then the version line. Strict at each step, so a
    future nudge that collapses two levels into one band fails here."""
    assert card_labels["title"] > card_labels["item"] > card_labels["meta"], card_labels

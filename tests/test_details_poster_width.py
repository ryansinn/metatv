"""Regression: the poster must not force the details content wider than the pane.

The "Cowboy Bebop genres/cast/version chips clip off the right edge" bug had a root
cause that three earlier fixes (What's New entries 92, 93, 103, 121) all missed because
they only ever measured ``_MetadataSection`` in isolation — which was never the culprit.

The real forcer is the **poster**.  ``_PosterLabel`` is a ``QLabel`` holding a pixmap;
with ``setScaledContents(False)`` and the default ``Preferred`` horizontal policy a
QLabel reports ``minimumSizeHint().width() == pixmap.width()``.  Inside the details
``QScrollArea`` (``setWidgetResizable(True)`` + horizontal scrollbar OFF) that floors
the whole content column at the pixmap width, so every section below is handed a
rectangle wider than the viewport and its flow rows wrap/clip beyond the right edge.

Fix: the poster label's horizontal size policy is ``Ignored`` so the layout disregards
its pixmap-driven width hint, and ``_rescale_current_image()`` re-fits the retained
original to whatever width the layout grants.

These tests pin the behaviour at the level that actually broke — the FULL content
composition inside the real scroll-area configuration — not a single section.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QScrollArea, QSizePolicy, QVBoxLayout, QWidget


_PANE_MIN_WIDTH = 300   # DetailsPaneWidget.setMinimumWidth(300)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def _poster_section(cfg):
    """A poster section displaying a tall (portrait) poster, like a real VOD poster."""
    from metatv.gui.details_sections import _PosterSection
    poster = _PosterSection(cfg, None)
    poster._display_poster(QPixmap(500, 750))  # 2:3 portrait, wider than any chip
    return poster


def test_poster_label_ignores_horizontal_width_hint(qapp):
    """The poster label opts OUT of driving width: its horizontal policy is Ignored,
    so a wide pixmap can't floor the content column."""
    poster = _poster_section(_make_config())
    assert (
        poster.poster_label.sizePolicy().horizontalPolicy()
        == QSizePolicy.Policy.Ignored
    ), "poster label must ignore its pixmap width hint so it never widens the pane"


def test_poster_section_does_not_force_content_width(qapp):
    """A poster section with a loaded portrait pixmap must NOT impose a minimum width —
    that minimum (== pixmap width) is exactly what dragged the whole pane over the
    viewport and clipped the genre/cast/version chips."""
    poster = _poster_section(_make_config())
    forced = poster.minimumSizeHint().width()
    assert forced <= _PANE_MIN_WIDTH, (
        f"poster section min width {forced}px must not exceed the {_PANE_MIN_WIDTH}px "
        "pane minimum — otherwise it forces every section below it wider than the viewport"
    )


def test_full_content_matches_narrow_viewport(qapp):
    """The end-to-end repro: poster + metadata + versions inside the real details
    scroll-area (resizable, h-scroll off).  At a narrow viewport the content widget
    must size to the VIEWPORT, not to the poster pixmap — proving nothing clips off
    the right edge."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.gui.details_versions import _VersionSection

    cfg = _make_config()
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(10, 10, 10, 10)
    poster = _poster_section(cfg)
    meta = _MetadataSection(cfg)
    ver = _VersionSection(cfg)
    for w in (poster, meta, ver):
        lay.addWidget(w)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    scroll.resize(320, 1200)   # a narrow pane, well under the 500px pixmap
    scroll.show()
    qapp.processEvents()
    qapp.processEvents()

    viewport_w = scroll.viewport().width()
    assert content.width() <= viewport_w + 1, (
        f"content width {content.width()}px exceeds the {viewport_w}px viewport — the "
        "poster is still forcing the column wider than the pane (chips would clip)"
    )


# A scene-release-style token with no spaces — a word-wrapped QLabel cannot break it at
# a space, so without the Ignored-horizontal opt-in it sets minimumSizeHint().width() to
# the whole token and floors the content column.  This is the SECOND forcer behind the
# Cowboy Bebop bug: only the variants whose plot/tagline carried such a token overflowed.
_LONG_TOKEN = "Cowboy.Bebop.1998.Complete.Series.1080p.BluRay.x265-EXAMPLEGROUP.PLUS.MORE"


def _full_pane(qapp, tmp_path):
    from metatv.core.image_cache import ImageCache
    from metatv.gui.details_pane import DetailsPaneWidget

    cfg = _make_config()
    ic = ImageCache(cache_dir=str(tmp_path / "imgcache"))
    pane = DetailsPaneWidget(cfg, ic, None)  # db=None → no EPG agenda
    for sec in (pane._poster, pane._meta, pane._plot, pane._cast, pane._tech):
        if hasattr(sec, "set_mode"):
            sec.set_mode(False)
    return pane


def test_wrapping_labels_opt_out_of_width(qapp, tmp_path):
    """Every word-wrapped text label in the details pane ignores its horizontal hint —
    so a long unbreakable token can't floor the content column at the token width."""
    pane = _full_pane(qapp, tmp_path)
    labels = [
        pane._plot.plot_label,
        pane._meta._tagline_lbl,
        pane._meta.rec_reason_label,
        pane._cast.cast_label,
        pane._cast._director_lbl,
        pane._tech.tech_details_label,
        pane._poster._country_info_lbl,
    ]
    for lbl in labels:
        assert lbl.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored, (
            f"{lbl.objectName() or lbl} must ignore its width hint so a long token "
            "(scene-release name / URL) can't widen the pane"
        )


def test_long_token_plot_does_not_force_content_width(qapp, tmp_path):
    """End-to-end repro of the 3-variants case: a plot/tagline with a long unbreakable
    token, plus a wide hi-res poster, must NOT widen the content past a narrow viewport."""
    pane = _full_pane(qapp, tmp_path)
    pane._plot.plot_label.setText(_LONG_TOKEN)
    pane._plot.plot_label.show()
    pane._meta._tagline_lbl.setText(_LONG_TOKEN)
    pane._meta._tagline_lbl.show()
    pane._poster._display_poster(QPixmap(680, 1000))

    pane.resize(300, 1800)
    pane.show()
    qapp.processEvents()
    qapp.processEvents()

    content = pane._content_layout.parentWidget()
    assert content.width() <= 301, (
        f"content width {content.width()}px exceeds the 300px pane — a long-token "
        "plot/tagline is still forcing the column wider than the viewport"
    )
    # And the token genuinely wraps to multiple lines rather than overflowing in one.
    plot = pane._plot.plot_label
    assert plot.heightForWidth(180) > plot.heightForWidth(2000), (
        "the long token must break across lines when the pane is narrow"
    )


# The poster box is a HARD FIXED height so the Play row below never moves between titles,
# and the poster is fit INSIDE it so its width can never exceed the card (hard right
# boundary). Side padding is acceptable; overflow is not.
from metatv.gui.details_sections import _PosterSection as _PS


def test_poster_box_height_is_fixed_across_widths(qapp, tmp_path):
    """The poster box stays a constant height at every pane width — so the Play/Watch
    Later buttons below never move between titles."""
    pane = _full_pane(qapp, tmp_path)
    pane.show()
    heights = []
    for w in (320, 410, 500):
        pane.resize(w, 1600)
        qapp.processEvents()
        pane._poster._display_poster(QPixmap(1004, 1498))  # measured Cowboy Bebop 2:3
        qapp.processEvents()
        qapp.processEvents()
        heights.append(pane._poster.poster_label.height())
    assert all(h == _PS._POSTER_FIXED_H for h in heights), (
        f"poster box height must be fixed at {_PS._POSTER_FIXED_H} at every width, got {heights}"
    )


def test_poster_never_exceeds_card_width(qapp, tmp_path):
    """At any width the poster pixmap fits WITHIN the card — never overflows the right
    edge (padding is fine, overflow is not)."""
    pane = _full_pane(qapp, tmp_path)
    pane.show()
    for w in (320, 410, 500):
        pane.resize(w, 1600)
        qapp.processEvents()
        pane._poster._display_poster(QPixmap(1004, 1498))
        qapp.processEvents()
        qapp.processEvents()
        lbl = pane._poster.poster_label
        pm = lbl.pixmap()
        assert pm is not None and not pm.isNull()
        assert pm.width() <= lbl.width() + 1, (
            f"poster pixmap {pm.width()} must not exceed card width {lbl.width()} at pane {w}"
        )
        assert pm.height() <= _PS._POSTER_FIXED_H + 1, (
            f"poster height {pm.height()} must fit the fixed box {_PS._POSTER_FIXED_H}"
        )


def test_content_reserves_right_gutter_for_scrollbar(qapp, tmp_path):
    """The content layout reserves a right gutter so nothing crosses the right edge / sits
    under the scrollbar (a hard right boundary)."""
    pane = _full_pane(qapp, tmp_path)
    m = pane._content_layout.contentsMargins()
    assert m.right() > m.left(), (
        f"right margin {m.right()} must exceed left {m.left()} to clear the scrollbar"
    )


# ---------------------------------------------------------------------------
# Placeholder alignment — measured from PAINTED PIXELS, not the alignment flag
# ---------------------------------------------------------------------------

class TestPosterPlaceholderIsCentred:
    """"No poster available" sat against the LEFT border of a large empty card
    for as long as the card has existed (owner: "it's always bothered me").

    The poster label is left-aligned on purpose — a pillarboxed portrait poster
    has to hug the left edge so the floating action rail overlays the art
    rather than the card margin — but that alignment also landed on the
    placeholder TEXT, which is a message about an empty card rather than an
    image being positioned inside one.

    Both tests below measure the ink actually painted. An assertion on
    ``alignment()`` would pass for a label whose text is centred in a box that
    is itself off to one side, which is a different rendering entirely.
    """

    WIDTH = 240
    HEIGHT = 80

    @classmethod
    def _render(cls, label):
        from PyQt6.QtGui import QColor, QImage

        label.resize(cls.WIDTH, cls.HEIGHT)
        image = QImage(label.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        label.render(image)
        return image

    @classmethod
    def _content_bounds(cls, label):
        """(left, right) x-bounds of the ink this label's CONTENT paints.

        Measured as the difference between the label rendered with its content
        and the same label rendered empty, so the widget's own background —
        which covers every pixel and would otherwise read as ink from edge to
        edge — cancels out.
        """
        with_content = cls._render(label)
        label.clear()
        empty = cls._render(label)
        xs = [x for x in range(with_content.width())
              for y in range(with_content.height())
              if with_content.pixelColor(x, y) != empty.pixelColor(x, y)]
        assert xs, "the label's content painted nothing at all"
        return min(xs), max(xs)

    def test_placeholder_text_is_horizontally_centred(self, qapp):
        """PRE-FIX THIS FAILED: the text started ~4px from the left border of a
        360px-wide card, leaving a ~230px gap on the right."""
        from metatv.gui.details_sections import _PosterLabel

        label = _PosterLabel()
        label.setText("No poster available")
        left, right = self._content_bounds(label)
        left_margin, right_margin = left, self.WIDTH - 1 - right
        assert abs(left_margin - right_margin) <= 2, (
            f"placeholder is not centred: {left_margin}px of space on the left, "
            f"{right_margin}px on the right"
        )
        # Non-zero on BOTH sides: a "margins are equal" check alone is satisfied
        # by text that fills the card edge to edge, and by 0 == 0.
        assert left_margin > 0 and right_margin > 0

    def test_poster_art_still_hugs_the_left_edge(self, qapp):
        """The other half of the rule, which the fix must not break: real art
        stays left-aligned so the action rail overlays the poster."""
        from PyQt6.QtGui import QColor, QPixmap

        from metatv.gui.details_sections import _PosterLabel

        art = QPixmap(60, 40)
        art.fill(QColor("#ff00ff"))
        label = _PosterLabel()
        label.setPixmap(art)
        left, right = self._content_bounds(label)
        assert left == 0, f"poster art starts {left}px in — it must hug the left edge"
        assert right < self.WIDTH - 1, (
            "art should leave its pillarbox padding on the RIGHT"
        )

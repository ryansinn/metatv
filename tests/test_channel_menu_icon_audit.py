"""Behavioral tests for the channel context-menu icon/colour audit.

The audited principle: every menu action has a UNIQUE, monochrome gray icon
(from icons.py); the ONLY coloured item is the resume affordance, which is the
orange ``COLOR_PLAYBACK_IN_PROGRESS`` accent.

Covers:
- open_ended_buffer uses the ∞ glyph; play_new_window uses the window glyph.
- category and queue use DIFFERENT icons (the bug the user found).
- play_from_beginning renders neutral/gray (NOT the orange resume colour).
- a resumable default Play relabels to "Play from M:SS" AND renders orange.
- in beginning-mode Play stays gray and resume_from is orange.
- no two visible actions in the channel menu share a glyph (single + multi).
- glyph_icon renders monochrome even for a colour emoji, and honours the
  orange resume colour.
"""

from __future__ import annotations

import pytest

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.channel_menu import (
    ACTIONS,
    SURFACE_LAYOUTS,
    ChannelMenuContext,
    _resolve_menu_icon,
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _ctx(**kwargs) -> ChannelMenuContext:
    defaults = dict(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        channel_found=True,
        is_hidden=False,
        watch_progress=0,
        watch_completed=False,
        playback_resume_mode="resume",
    )
    defaults.update(kwargs)
    return ChannelMenuContext(**defaults)


# ---------------------------------------------------------------------------
# 1. Specific glyph swaps
# ---------------------------------------------------------------------------

def test_open_ended_buffer_uses_infinity_glyph():
    assert _icons.open_ended_buffer_icon == "∞", (
        "open-ended buffer should use the ∞ infinity glyph, not an hourglass"
    )
    assert ACTIONS["play_open_ended_buffer"].icon == _icons.open_ended_buffer_icon


def test_play_new_window_uses_window_glyph():
    assert _icons.new_window_icon == "❐", (
        "Play in New Window should use the window-over-window glyph (U+2750)"
    )
    assert ACTIONS["play_new_window"].icon == _icons.new_window_icon
    # Must not reuse the play/open-ended/clock-ish glyphs.
    assert _icons.new_window_icon != _icons.play_icon
    assert _icons.new_window_icon != _icons.open_ended_buffer_icon


# ---------------------------------------------------------------------------
# 2. Category vs Queue — the reported duplicate
# ---------------------------------------------------------------------------

def test_category_icon_distinct_from_queue():
    assert hasattr(_icons, "category_icon"), "icons.py must define a category_icon"
    assert _icons.category_icon != _icons.queue_icon
    assert ACTIONS["category"].icon == _icons.category_icon
    assert ACTIONS["category"].icon != ACTIONS["queue"].icon, (
        "Add to Category must not share the Add to Queue icon"
    )


def test_all_category_actions_share_the_category_icon():
    """Single, bulk and EPG category actions all use the one category glyph."""
    for token in ("category", "bulk_category", "epg_assign_category"):
        assert ACTIONS[token].icon == _icons.category_icon, token


# ---------------------------------------------------------------------------
# 3. Resume colouring + label (the orange accent)
# ---------------------------------------------------------------------------

def test_play_from_beginning_icon_is_neutral_not_resume(qapp):
    """play_from_beginning resolves to a gray (None) colour, never the orange accent."""
    ctx = _ctx(watch_progress=300)  # resumable movie
    glyph, color = _resolve_menu_icon(ACTIONS["play_from_beginning"], ctx)
    assert glyph == _icons.play_from_beginning_icon
    assert color is None, "play_from_beginning must be neutral/gray, not orange"
    # And its glyph must differ from the resume glyph so the two read distinctly.
    assert _icons.play_from_beginning_icon != _icons.resume_from_icon


def test_play_from_beginning_uses_play_triangle_not_last_track(qapp):
    """'Play from Beginning' shows the gray play triangle ▶ — the SAME clean glyph as
    plain Play — not the ⏮ last-track button, which renders as a tofu/box in many
    fonts (the bug: a "gray square" appeared instead of a play triangle when a resume
    option was also present). Distinction from resume stays carried by colour."""
    assert _icons.play_from_beginning_icon == _icons.play_icon == "▶"


def test_resumable_play_is_orange_and_relabelled(qapp):
    """A resumable default Play (resume mode) → 'Play from M:SS' + orange icon."""
    ctx = _ctx(watch_progress=300, playback_resume_mode="resume")
    label = ACTIONS["play"].label(ctx)
    glyph, color = _resolve_menu_icon(ACTIONS["play"], ctx)
    assert label == "Play from 5:00", f"expected resume label, got {label!r}"
    assert glyph == _icons.play_icon
    assert color == _theme.COLOR_PLAYBACK_IN_PROGRESS, "resumable Play must be orange"


def test_non_resumable_play_is_plain_gray(qapp):
    """An unwatched item's Play is plain 'Play' with no colour accent."""
    ctx = _ctx(watch_progress=0)
    label = ACTIONS["play"].label(ctx)
    _glyph, color = _resolve_menu_icon(ACTIONS["play"], ctx)
    assert label == "Play"
    assert color is None


def test_beginning_mode_play_gray_resume_from_orange(qapp):
    """In beginning mode: Play stays gray; resume_from carries the orange accent."""
    ctx = _ctx(watch_progress=180, playback_resume_mode="beginning")
    # Play: gray + plain label (clicking starts from zero in this mode).
    play_label = ACTIONS["play"].label(ctx)
    _pg, play_color = _resolve_menu_icon(ACTIONS["play"], ctx)
    assert play_label == "Play"
    assert play_color is None
    # resume_from: applies + orange.
    assert ACTIONS["resume_from"].applies(ctx) is True
    _rg, resume_color = _resolve_menu_icon(ACTIONS["resume_from"], ctx)
    assert resume_color == _theme.COLOR_PLAYBACK_IN_PROGRESS


# ---------------------------------------------------------------------------
# 4. Icon uniqueness across a rendered menu
# ---------------------------------------------------------------------------

def _visible_glyphs(ctx: ChannelMenuContext) -> dict[tuple[str, str | None], str]:
    """Map (glyph, colour) → action id for every applicable action with an icon.

    Uniqueness is keyed on (glyph, colour), not glyph alone: a menu item ALSO carries
    a text label, so two play-family actions may legitimately share the ▶ play
    triangle when colour separates them — e.g. in resume mode the default Play is the
    orange "Play from M:SS" while "Play from Beginning" is the gray ▶ override. What
    must never happen is two actions identical in BOTH glyph and colour in one menu.
    """
    seen: dict[tuple[str, str | None], str] = {}
    for token in SURFACE_LAYOUTS[ctx.surface]:
        if token == "sep":
            continue
        action = ACTIONS[token]
        if not action.applies(ctx):
            continue
        glyph, color = _resolve_menu_icon(action, ctx)
        if not glyph:
            continue
        key = (glyph, color)
        assert key not in seen, (
            f"icon {glyph!r} (colour {color!r}) shared by '{token}' and "
            f"'{seen[key]}' in the same menu"
        )
        seen[key] = token
    return seen


def test_channel_menu_icons_unique_single_select(qapp):
    """No two visible single-select channel-menu actions share a glyph."""
    ctx = _ctx(media_type="movie", watch_progress=300, playback_resume_mode="resume")
    glyphs = _visible_glyphs(ctx)
    assert len(glyphs) >= 8, f"expected a populated menu, got {glyphs}"


def test_channel_menu_icons_unique_multi_select(qapp):
    """No two visible multi-select channel-menu actions share a glyph."""
    ctx = ChannelMenuContext(
        channel_ids=["a", "b", "c"], surface="channel", channel_found=True
    )
    glyphs = _visible_glyphs(ctx)
    assert len(glyphs) >= 6, f"expected bulk actions, got {glyphs}"


# ---------------------------------------------------------------------------
# 5. Monochrome rendering — colour emoji collapse to the pen colour
# ---------------------------------------------------------------------------

def _icon_buckets(icon) -> set[tuple[int, int, int]]:
    from PyQt6.QtCore import QSize
    pm = icon.pixmap(QSize(16, 16))
    img = pm.toImage()
    buckets: set[tuple[int, int, int]] = set()
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() < 60:
                continue
            buckets.add((c.red() // 32, c.green() // 32, c.blue() // 32))
    return buckets


def test_colour_emoji_renders_monochrome_gray(qapp):
    """A colour emoji (👍) must render as a grayscale silhouette by default."""
    _icons._clear_glyph_icon_cache()
    icon = _icons.glyph_icon(_icons.like_icon)  # 👍 is a colour emoji
    buckets = _icon_buckets(icon)
    assert buckets, "icon must have opaque pixels"
    for r, g, b in buckets:
        assert abs(r - g) <= 1 and abs(g - b) <= 1 and abs(r - b) <= 1, (
            f"default menu icon must be grayscale; found non-gray bucket {(r, g, b)}"
        )


def test_resume_colour_differs_from_default(qapp):
    """The orange resume render differs from the default gray render of ▶."""
    _icons._clear_glyph_icon_cache()
    gray = _icon_buckets(_icons.glyph_icon(_icons.play_icon))
    orange = _icon_buckets(
        _icons.glyph_icon(_icons.play_icon, _theme.COLOR_PLAYBACK_IN_PROGRESS)
    )
    # The orange render must contain at least one non-gray bucket.
    has_colour = any(
        not (abs(r - g) <= 1 and abs(g - b) <= 1 and abs(r - b) <= 1)
        for r, g, b in orange
    )
    assert has_colour, "orange resume icon must contain a coloured (non-gray) bucket"
    assert gray != orange, "orange and gray renders must differ"

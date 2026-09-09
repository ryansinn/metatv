"""Every semantic icon role resolves, and no two roles render identically.

A name check cannot catch a collision — ``mdi6.cancel`` and
``mdi6.block-helper`` are different keys that draw the same circle-and-slash,
which is how ``hide`` and ``not_interested`` ended up indistinguishable in the
first draft. This renders each key and compares the actual pixels.
"""
from __future__ import annotations

import os
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("qtawesome")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def _app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_every_role_resolves(_app) -> None:
    from metatv.gui import icons, icon_utils
    unresolved = [
        f"{role} -> {key}"
        for role, key in icons.VECTOR_KEYS.items()
        if icon_utils.resolve_icon(key, color="#b0b4ba").isNull()
    ]
    assert not unresolved, "icon keys that render nothing:\n  " + "\n  ".join(unresolved)


def test_no_two_roles_render_the_same_glyph(_app) -> None:
    from metatv.gui import icons, icon_utils
    seen: dict[bytes, str] = {}
    collisions: list[str] = []
    for role, key in icons.VECTOR_KEYS.items():
        img = icon_utils.resolve_icon(key, color="#ffffff").pixmap(24, 24).toImage()
        bits = bytes(img.constBits().asstring(img.sizeInBytes()))
        if bits in seen:
            collisions.append(f"{role} ({key}) is pixel-identical to {seen[bits]}")
        else:
            seen[bits] = f"{role} ({key})"
    assert not collisions, (
        "two roles cannot share a glyph — the user cannot tell them apart:\n  "
        + "\n  ".join(collisions)
    )


def test_icons_take_the_palette(_app) -> None:
    """The point of vector icons over emoji: they track the theme."""
    from metatv.gui import icons, icon_utils

    def _bits(color: str) -> bytes:
        img = icon_utils.resolve_icon(
            icons.vector_key("favorite"), color=color
        ).pixmap(24, 24).toImage()
        return bytes(img.constBits().asstring(img.sizeInBytes()))

    assert _bits("#ffffff") != _bits("#101010"), "icon ignored its colour argument"


def test_unknown_role_is_loud(_app) -> None:
    from metatv.gui import icons
    with pytest.raises(KeyError):
        icons.vector_key("no_such_role")


def test_expand_collapse_chevrons_point_the_correct_direction(_app) -> None:
    """CHV-2: closed sections render a RIGHT chevron, open ones a DOWN chevron.

    ``icons.VECTOR_KEYS["expand"]``/``["collapse"]`` had these swapped — every
    call site passes the role naming the ACTION AVAILABLE ("expand" for a
    closed section, "collapse" for an open one), so a closed section rendered
    a down chevron and an open one a right chevron: backwards against the
    universal disclosure convention (closed ▸, open ▾).

    This renders the actual pixels behind each role and compares them
    against the two chevron glyphs directly (not just "some icon, and it
    changed on toggle" — the token-existence check that let the inversion
    ship) — so a re-inversion, even one where both keys still resolve to a
    valid icon, fails this test.
    """
    from metatv.gui import icons, icon_utils

    def _bits(icon_key: str) -> bytes:
        img = icon_utils.resolve_icon(icon_key, color="#ffffff").pixmap(24, 24).toImage()
        return bytes(img.constBits().asstring(img.sizeInBytes()))

    expand_bits = _bits(icons.VECTOR_KEYS["expand"])
    collapse_bits = _bits(icons.VECTOR_KEYS["collapse"])
    right_bits = _bits("mdi6.chevron-right")
    down_bits = _bits("mdi6.chevron-down")

    assert expand_bits == right_bits, (
        "a CLOSED section's chevron (role 'expand') must render as the "
        "RIGHT-pointing mdi6.chevron-right glyph"
    )
    assert collapse_bits == down_bits, (
        "an OPEN section's chevron (role 'collapse') must render as the "
        "DOWN-pointing mdi6.chevron-down glyph"
    )
    assert expand_bits != collapse_bits, "closed and open must not share a glyph"

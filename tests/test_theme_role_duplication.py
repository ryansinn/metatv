"""No two theme roles may declare the same thing.

docs/AUDIT_2026-08-16.md found one clean signal: *every finding that shipped
with a mechanical guard stayed at zero; every finding that relied on discipline
alone regressed.* File sizes and ``get_session()`` counts got a ratchet. Role
duplication did not — so it regressed.

Concretely: ``SIDEBAR_OVERFLOW_BTN`` was added beside ``RECIPE_SAVED_ICON_BTN``
(both a flat transparent icon button that brightens on hover),
``SIDEBAR_ACTION_RING`` beside ``PANEL_BTN`` (both a bordered button), and
``SIDEBAR_TOGGLE_BTN`` beside ``SIDEBAR_SUBSECTION_TOGGLE`` (both a borderless
chevron). Three roles, three existing equivalents, in one session — and CLAUDE.md
already says a stylesheet used by more than one widget is a shared role
constant, never copy-pasted.

The check is on the DECLARED PROPERTIES, not the rendered string: two roles that
differ only by a colour token are still two roles doing one job, and comparing
rendered text would miss that while flagging every palette switch.
"""

from __future__ import annotations

import re
from collections import defaultdict

import pytest

from metatv.gui import theme as _theme

#: Roles that are deliberately identical — a pair whose SAMENESS is the point,
#: so making one a reference to the other would hide the intent. Keep this list
#: short and justified; it is not a place to park a duplicate you did not want
#: to fix.
_ALLOWED_TWINS: set[frozenset[str]] = set()


def _properties(sheet: str) -> frozenset[str]:
    """The CSS property NAMES a role declares, ignoring their values.

    Values carry the palette and change on every theme switch; the shape of a
    role — "a border, a radius, a padding and a font size" — is what makes two
    roles the same job.
    """
    return frozenset(
        m.group(1).strip().lower()
        for m in re.finditer(r"([a-z-]+)\s*:", sheet or "")
    )


def _role_names() -> list[str]:
    return [
        name for name in dir(_theme)
        if name.isupper()
        and not name.startswith(("COLOR_", "FONT_", "OVERLAY_", "RADIUS_",
                                 "SPACE_", "SHADOW_"))
        and isinstance(getattr(_theme, name), str)
        and ":" in getattr(_theme, name)
    ]


def test_byte_identical_role_groups_do_not_grow():
    """A ratchet, not a zero — because the debt is already 25 groups deep.

    Measured on arrival: 299 roles, 25 sets that are byte-identical, the worst
    holding TWELVE names for one stylesheet (CHANNEL_NAME_DIM, TIME_LABEL,
    DIAG_URL, NAV_HEALTH, EVENTS_TIME_HINT, …). Asserting zero would be red on
    day one and get deleted; asserting "no more than today" makes every new
    duplicate somebody's explicit decision.

    Lower the budget when roles are merged. Never raise it.
    """
    by_sheet: dict[str, list[str]] = defaultdict(list)
    for name in _role_names():
        by_sheet[getattr(_theme, name)].append(name)

    groups = sorted(
        (sorted(names) for names in by_sheet.values()
         if len(names) > 1 and frozenset(names) not in _ALLOWED_TWINS),
        key=len, reverse=True,
    )
    assert len(groups) <= _IDENTICAL_GROUP_BUDGET, (
        f"{len(groups)} groups of byte-identical roles, up from "
        f"{_IDENTICAL_GROUP_BUDGET}. Point the new call site at the role that "
        f"already says this instead of adding a twin. Largest groups: "
        f"{groups[:3]}"
    )


@pytest.mark.parametrize("palette", ["Midnight", "Daylight"])
def test_roles_that_declare_the_same_properties_are_reviewed(palette):
    """A softer net: same property SET and same selector shape.

    Not every match is a bug — two chips can legitimately declare
    ``color/border/border-radius/padding/font-size`` and mean different things.
    So this asserts the count does not GROW, ratchet-style, rather than that it
    is zero: the existing pairs are the debt, and the next one has to be
    justified rather than merged into the pile.
    """
    before = _theme.current_theme()
    try:
        _theme.apply_theme(palette)
        by_shape: dict[tuple, list[str]] = defaultdict(list)
        for name in _role_names():
            sheet = getattr(_theme, name)
            selector = tuple(sorted(set(re.findall(r"([A-Z][A-Za-z]+)\s*[#{:]", sheet))))
            by_shape[(_properties(sheet), selector)].append(name)

        clusters = sum(1 for names in by_shape.values() if len(names) > 1)
        assert clusters <= _SHAPE_CLUSTER_BUDGET, (
            f"{palette}: {clusters} groups of roles now declare the same "
            f"properties on the same selector, up from {_SHAPE_CLUSTER_BUDGET}. "
            f"Reuse an existing role instead of adding a near-twin — see this "
            f"module's docstring for the three that prompted it."
        )
    finally:
        _theme.apply_theme(before)


#: Shrink-only, like the code-health ratchet. Lower these when roles are merged;
#: never raise one to make a new twin pass. Measured 2026-08-25 on 299 roles.
_IDENTICAL_GROUP_BUDGET = 25
# 41 -> 42, justified rather than absorbed, which is what this ratchet asks for.
#
# The new cluster is SIDEBAR_GROUP_HEADING / SIDEBAR_GROUP_HEADING_COUNT /
# SIDEBAR_ROW_NEWS. They declare the same property NAMES (color, font-size,
# font-weight, background) on the same selector, and this test compares names
# rather than values — but every value differs, and deliberately:
#
#   heading  small-caps, letter-spaced, secondary weight, COLOR_TEXT
#   count    a size up, bold, COLOR_TEXT_HI — the count carries the emphasis
#   news     the accent, because news is the one thing worth looking at
#
# That two-tone contrast IS the design (see GroupHeading's docstring), so
# collapsing them into one role would delete the thing they exist to express.
# The heading joined the cluster when its colour moved OFF COLOR_MUTED — muted
# measured 4.15:1 and failed the 4.5 text floor in four of six palettes — which
# is a fix, not debt.
# 42 -> 43, justified rather than absorbed.
#
# The new cluster is LOG_STREAM / QA_FAIL_NOTE_BOX. Both declare background,
# color, border, border-radius, padding and font-size on QPlainTextEdit — the
# same property NAMES, which is what this test compares — and every value
# differs, because they are opposite kinds of surface:
#
#   LOG_STREAM         the deepest app ground and a neutral border: a full-panel
#                      wall of dense monospace in its own window, where the
#                      darkest ground gives the smallest legible type the most
#                      contrast to work with
#   QA_FAIL_NOTE_BOX   an error TINT and an error border: a small inline box
#                      revealed beneath a failed step, where the colour is the
#                      signal
#
# Merging them would paint the log viewer as a failure notice. Kept apart.
_SHAPE_CLUSTER_BUDGET = 43

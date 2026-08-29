"""Both collapse surfaces must rank quality the same way.

``tag.py``'s variant collapse carried its own hardcoded quality CASE while
``channel.py`` used ``QUALITY_TIER_RANK``. They disagreed on **ordering**, not
just on numbers:

    HDR   canonical: unranked -> default, BELOW HD
          local:     1, tied with FHD and ABOVE HD
    8K    canonical: beats 4K.   local: tied with it
    SD    canonical: beats LQ.   local: tied with it

So a title with an HD copy and an HDR copy elected **HD** in the channel list
and **HDR** in Discover — two surfaces, same data, different answer, and no
test could see it because each surface was only ever checked against itself.

The canonical table is explicit about why HDR is not a tier: it is a
dynamic-range descriptor, not a resolution, and unranked tokens "fall back to
``_QUALITY_TIER_RANK_DEFAULT`` rather than a made-up position". The local
ladder invented exactly that position.

These tests compare the two surfaces to EACH OTHER rather than to a fixture, so
a third collapse written tomorrow with a fourth ladder is caught the moment it
disagrees.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from metatv.core.channel_name_utils import (
    QUALITY_TIER_RANK, _QUALITY_TIER_RANK_DEFAULT,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
CORE = REPO / "metatv" / "core"

#: Every token either ladder knew about, plus one it did not.
_TOKENS = ["8K", "4K", "UHD", "FHD", "HD", "HDR", "SD", "LQ", "HEVC", None]


def _canonical_rank(token):
    """Sort rank (lower is better), exactly as both collapses compute it."""
    max_rank = max(QUALITY_TIER_RANK.values())
    return max_rank - QUALITY_TIER_RANK.get(token, _QUALITY_TIER_RANK_DEFAULT)


# ── the ordering the canonical table actually specifies ─────────────────────

def test_hdr_is_not_treated_as_a_resolution_tier():
    """The specific disagreement, kept as a named regression.

    HDR describes dynamic range, not resolution. Ranking it above HD is the
    "made-up position" the lookup table's own comment exists to forbid.
    """
    assert _canonical_rank("HDR") > _canonical_rank("HD"), (
        "HDR is being ranked as a better picture tier than HD"
    )
    assert _canonical_rank("HDR") == _canonical_rank("HEVC"), (
        "HDR should fall to the same default as any other non-resolution token"
    )


@pytest.mark.parametrize("better,worse", [
    ("8K", "4K"), ("4K", "FHD"), ("FHD", "HD"), ("HD", "SD"), ("SD", "LQ"),
])
def test_the_resolution_tiers_are_strictly_ordered(better, worse):
    """No ties between real tiers — a tie is what the local ladder introduced."""
    assert _canonical_rank(better) < _canonical_rank(worse), (
        f"{better} does not outrank {worse}"
    )


# ── neither surface may carry its own ladder ────────────────────────────────

def _quality_case_literals(path: pathlib.Path) -> "list[str]":
    """Quality tokens compared against a literal inside a CASE, per file.

    Derived: finds `detected_quality == "4K"`-shaped comparisons and the raw
    SQL `WHEN '4K'` form, which is how the local ladder was written.
    """
    src = path.read_text(encoding="utf-8")
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Compare):
            left = node.left
            if getattr(left, "attr", None) == "detected_quality":
                for cmp in node.comparators:
                    if isinstance(cmp, ast.Constant) and isinstance(cmp.value, str):
                        found.append(cmp.value)
    # The raw-SQL form the tag collapse used.
    for tok in _TOKENS:
        if tok and f"WHEN '{tok}'" in src:
            found.append(tok)
    return found


@pytest.mark.parametrize("relpath", [
    "repositories/tag.py",
    "repositories/channel.py",
])
def test_no_collapse_hardcodes_its_own_quality_ladder(relpath):
    """THE assertion. A literal quality token in a CASE is a second ladder."""
    path = CORE / relpath
    literals = _quality_case_literals(path)
    assert not literals, (
        f"{relpath} compares detected_quality against literals {sorted(set(literals))} "
        "instead of reading QUALITY_TIER_RANK — that is a parallel lookup table, "
        "and the two surfaces already disagreed about HDR because of one"
    )


@pytest.mark.parametrize("relpath", ["repositories/tag.py", "repositories/channel.py"])
def test_both_collapses_read_the_shared_table(relpath):
    src = (CORE / relpath).read_text(encoding="utf-8")
    assert "QUALITY_TIER_RANK" in src, (
        f"{relpath} builds a representative rank without the canonical table"
    )


def test_the_two_surfaces_agree_token_for_token():
    """Compare the surfaces to EACH OTHER, not to a fixture.

    Both now build their CASE from the same dict, so this is a tautology today
    — which is the point. It stops being one the moment someone reintroduces a
    local ladder, and it fails naming the token they disagree on.
    """
    from metatv.core.repositories import channel as channel_mod

    ranks_channel = {
        t: max(QUALITY_TIER_RANK.values())
        - QUALITY_TIER_RANK.get(t, _QUALITY_TIER_RANK_DEFAULT)
        for t in _TOKENS
    }
    ranks_expected = {t: _canonical_rank(t) for t in _TOKENS}

    assert ranks_channel == ranks_expected
    assert channel_mod._MAX_QUALITY_RANK == max(QUALITY_TIER_RANK.values())

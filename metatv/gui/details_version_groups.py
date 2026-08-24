"""Sixty-five chips become eight, without losing a single version.

Kraven The Hunter carries **65 versions across 19 regions**; Nickelodeon 94
across 32. Rendered one chip per version — which is what "Also available" did —
that is a wall you cannot read and cannot act on, and it is the common case for
anything popular rather than an edge case.

Grouping by region collapses it. The grouping key is
``detected_region or detected_prefix``, decided against the real library rather
than assumed:

    region only         17 regions, 57 of 65 placed,  8 unplaced
    region or prefix    19 regions, 65 of 65 placed,  0 unplaced   ← this one
    prefix or region    24 regions, 65 of 65 placed,  0 unplaced

Region alone strands eight versions. Prefix first over-splits, because a prefix
is often a language where a region is also recorded (DE splits 9 → 6). Region
with prefix as the fallback places everything and keeps the strongest grouping.

Grouping by *language* was considered and does not work at all:
``detected_collection_language`` is empty across the whole Nickelodeon group.

No version is ever dropped. A header that says "65 versions" and a grid that
accounts for 57 of them is worse than no grouping, so anything with neither
field lands in an explicit bucket rather than falling out of the count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

#: Bucket for a version carrying neither a region nor a prefix. Named, not
#: hidden — see the module docstring.
UNKNOWN_REGION = "??"

#: Region chips shown before the "+N more" tail. Twelve fills two rows at the
#: details pane's width without the grid becoming the wall it replaced.
DEFAULT_VISIBLE_REGIONS = 12

#: Below this many versions, DO NOT GROUP — show them flat, as before.
#:
#: Grouping trades detail for scale, and that trade is only worth making at
#: scale. A title with three versions rendered as three region chips costs a
#: click to reach any of them and hides the source icon and quality tier that
#: made the flat chip useful. Twelve flat chips are still readable; sixty-five
#: are not, which is the case this whole module exists for.
GROUPING_THRESHOLD = 12


@dataclass(frozen=True)
class RegionGroup:
    """Every version that shares a region, and what to say about them.

    Attributes:
        code:      The region/prefix code, or ``UNKNOWN_REGION``.
        versions:  The versions themselves — nothing is summarised away, so the
                   per-version context menu still has something to act on.
        qualities: Distinct quality tiers present, best-known order preserved.
    """

    code: str
    versions: tuple
    qualities: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.versions)


def region_key(version) -> str:
    """The region a version belongs to. Never empty."""
    code = (getattr(version, "detected_region", None)
            or getattr(version, "detected_prefix", None)
            or "")
    return code.upper() if code else UNKNOWN_REGION


def group_by_region(versions: Iterable) -> list[RegionGroup]:
    """Collapse versions into region groups, biggest first.

    Ties break alphabetically so the grid is stable between renders — a chip
    that moves when nothing changed is a chip you cannot learn the position of.
    ``UNKNOWN_REGION`` always sorts last regardless of size: it is the bucket
    for what could not be identified, and it should not head the list.
    """
    buckets: dict[str, list] = {}
    for version in versions:
        buckets.setdefault(region_key(version), []).append(version)

    groups = [
        RegionGroup(
            code=code,
            versions=tuple(members),
            qualities=_distinct_qualities(members),
        )
        for code, members in buckets.items()
    ]
    groups.sort(key=lambda g: (g.code == UNKNOWN_REGION, -g.count, g.code))
    return groups


def _distinct_qualities(versions: Sequence) -> tuple[str, ...]:
    """Quality tiers present in a region, first-seen order, blanks dropped."""
    seen: list[str] = []
    for version in versions:
        quality = (getattr(version, "detected_quality", None) or "").upper()
        if quality and quality not in seen:
            seen.append(quality)
    return tuple(seen)


def summarise(groups: Sequence[RegionGroup]) -> str:
    """The header's right-hand count — "65 versions · 19 regions"."""
    versions = sum(g.count for g in groups)
    regions = len(groups)
    return (f"{versions} version{'s' if versions != 1 else ''} · "
            f"{regions} region{'s' if regions != 1 else ''}")

"""What is actually being filtered, said in a handful of words.

The ``Includes:`` column answers "what *could* you filter by" — ten ALL-CAPS
facets, most of them all-ticked and therefore constraining nothing, occupying a
fixed ~250px whether or not you are filtering. This module answers the other
question, the one you actually have while looking at a result list: **what is
being filtered right now.**

Usually the answer is "nothing", and it takes no space to say so. When it is
something, it is one or two chips.

The conversion lives here, apart from Qt, because it is the part with rules in
it — which facets count as active, how several values collapse into one label,
which order they read in. ``filter_chip_bar.py`` only draws the result.

The input is the resolved dict from ``FilterPanel.get_filter_state()``, so the
chips can never disagree with the query: both sides read the same object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

#: Facet order down the chip line. Media leads because it is the coarsest cut,
#: then the panel's own section order, then hide-watched, which is a mode rather
#: than a facet and reads best last.
FACET_ORDER: tuple[str, ...] = (
    "language", "region", "platform", "quality",
    "category", "genre", "subtitle", "dub", "format",
)

#: What a facet is called on a chip. Deliberately shorter than the panel's
#: section titles: the chip already carries a value, so "Subtitle Language:
#: English" would say "language" twice.
FACET_TITLES: Mapping[str, str] = {
    "language": "Language",
    "region":   "Region",
    "platform": "Platform",
    "quality":  "Quality",
    "category": "Category",
    "genre":    "Genre",
    "subtitle": "Subtitles",
    "dub":      "Dub",
    "format":   "Audio",
}

#: The three media kinds, and the words for them. ``MEDIA_ALL`` is the
#: unconstrained set — matching it exactly is what "no media filter" means.
MEDIA_ALL: frozenset[str] = frozenset({"live", "movie", "series"})
MEDIA_TITLES: Mapping[str, str] = {
    "live": "Live TV", "movie": "Movies", "series": "Series",
}

#: Values named on one chip before it collapses to "First +N". Two fit on a line
#: at a readable width; three start pushing the rest of the chips off it.
_NAMED_VALUES = 2


@dataclass(frozen=True)
class FilterChip:
    """One active constraint, ready to draw.

    Attributes:
        facet:   What removing this chip should unconstrain. Either a panel
                 section key (``"language"``), a single media kind
                 (``"media:movie"``), or ``"hide_watched"``.
        label:   The chip's text.
        tooltip: The long form — every value, when the label had to summarise.
    """

    facet: str
    label: str
    tooltip: str


def _summarise(title: str, labels: Sequence[str]) -> tuple[str, str]:
    """Collapse a facet's selected values into (label, tooltip).

    One value speaks for itself: a chip reading ``4K`` needs no "Quality:"
    in front of it, and dropping the prefix is what keeps the line short
    enough to be worth having. Past that the facet name has to come back,
    because ``English +6`` alone does not say *which* language axis — the
    panel has three of them (spoken, subtitle, dub).
    """
    if len(labels) == 1:
        return labels[0], f"{title}: {labels[0]}"
    named = ", ".join(labels[:_NAMED_VALUES])
    rest = len(labels) - _NAMED_VALUES
    full = ", ".join(labels)
    if rest <= 0:
        return f"{title}: {named}", f"{title}: {full}"
    return f"{title}: {named} +{rest}", f"{title}: {full}"


def describe_active_filters(
    state: Mapping[str, object],
    *,
    label_for: Callable[[str, str], str] | None = None,
    facet_totals: Mapping[str, int] | None = None,
) -> list[FilterChip]:
    """Turn a resolved filter state into the chips that describe it.

    Args:
        state: The dict from ``FilterPanel.get_filter_state()``.
        label_for: ``(facet, key) -> display label``. Facet values are stored as
            keys (``"en"``, ``"4k"``) and shown as labels (``"English"``,
            ``"4K"``); the panel's sections hold that mapping. Defaults to the
            key itself, which is what tests without a panel want.
        facet_totals: ``facet -> how many values that facet has``. Used to tell
            "every value ticked, but untagged content excluded" apart from a
            real value constraint — the two are indistinguishable in
            ``tag_includes``, which carries a full value set in both cases.

    Returns:
        Chips in reading order. Empty when nothing is constrained.
    """
    resolve = label_for or (lambda _facet, key: key)
    totals = facet_totals or {}
    chips: list[FilterChip] = []

    # ── Media ────────────────────────────────────────────────────────────────
    # One chip per kind rather than one "Media: Movies, Series" chip: the kinds
    # are the filter people reach for most, and being able to drop *one* of two
    # without opening the panel is the whole point of a removable chip.
    media = set(state.get("media_types") or ())
    if media and media != set(MEDIA_ALL):
        for kind in ("live", "movie", "series"):
            if kind in media:
                title = MEDIA_TITLES[kind]
                chips.append(FilterChip(
                    facet=f"media:{kind}",
                    label=title,
                    tooltip=f"Showing {title} — click × to stop filtering by kind",
                ))

    # ── Facets ───────────────────────────────────────────────────────────────
    tag_includes: Mapping[str, Iterable[str]] = state.get("tag_includes") or {}
    hiding_untagged = set(state.get("facets_hiding_untagged") or ())

    for facet in FACET_ORDER:
        selected = tag_includes.get(facet)
        untagged_hidden = facet in hiding_untagged
        if not selected and not untagged_hidden:
            continue
        title = FACET_TITLES.get(facet, facet.title())
        keys = sorted(selected or ())
        total = totals.get(facet)

        # Every value ticked and the chip still exists → the constraint is not
        # about values at all, it is the untagged footer being off. Saying
        # "Language: English +40" there would be a lie about what is filtering.
        if untagged_hidden and total is not None and len(keys) >= total:
            chips.append(FilterChip(
                facet=facet,
                label=f"{title}: tagged only",
                tooltip=(f"Every {title.lower()} value is included, but content "
                         f"with no {title.lower()} tag is hidden"),
            ))
            continue

        labels = sorted(resolve(facet, k) for k in keys)
        label, tooltip = _summarise(title, labels)
        if untagged_hidden:
            tooltip += "  ·  untagged hidden"
        chips.append(FilterChip(facet=facet, label=label, tooltip=tooltip))

    # ── Modes ────────────────────────────────────────────────────────────────
    if state.get("hide_watched"):
        chips.append(FilterChip(
            facet="hide_watched",
            label="Hide watched",
            tooltip="Movies and series you have marked watched are hidden",
        ))

    return chips

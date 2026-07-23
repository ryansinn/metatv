"""Recipe state — the saved-recipe data model + rating-scale constants.

A "recipe" is a faceted query: include/exclude tag values plus (as of the
rating-range ingredient) a ``(min, max)`` band on the 0–10 rating scale.  This
module owns:

- the canonical rating-scale endpoints (:data:`RATING_SCALE_MIN` /
  :data:`RATING_SCALE_MAX`) — the single source of truth referenced by both the
  repository filter (``core/repositories/tag.py``) and the slider widget
  (``gui/rating_range_slider.py``);
- serialization to/from a plain JSON/YAML-friendly ``dict`` for persistence in
  ``Config.recipe_saved``.

**Backward compatibility (the load-old-recipes rule):** a serialized recipe
written before the rating axis existed has no ``rating_range`` key;
:func:`deserialize_recipe` fills it with the full span, i.e. "no rating filter",
so old saved recipes keep matching exactly what they used to.

No Qt / no DB dependency — pure data, so it round-trips in a unit test without a
running app.
"""

from __future__ import annotations

from typing import Any, Dict, Set, Tuple

# Canonical rating scale (single source of truth for the recipe rating axis).
RATING_SCALE_MIN: float = 0.0
RATING_SCALE_MAX: float = 10.0

#: The full-span band — imposes no rating constraint (includes unrated content).
DEFAULT_RATING_RANGE: Tuple[float, float] = (RATING_SCALE_MIN, RATING_SCALE_MAX)


def rating_range_is_full(rating_range: Tuple[float, float] | None) -> bool:
    """Return True when *rating_range* imposes no constraint.

    A band whose floor is at/below the scale minimum and whose ceiling is
    at/above the scale maximum (and ``None``) selects everything, unrated
    included.
    """
    if rating_range is None:
        return True
    lo, hi = rating_range
    return lo <= RATING_SCALE_MIN and hi >= RATING_SCALE_MAX


def _sets_to_lists(mapping: Dict[str, Set[str]]) -> Dict[str, list]:
    """Convert ``{facet: set[value]}`` → ``{facet: sorted[value]}`` (only non-empty)."""
    return {ftype: sorted(vals) for ftype, vals in mapping.items() if vals}


def _lists_to_sets(mapping: Any) -> Dict[str, Set[str]]:
    """Convert a stored ``{facet: [value, …]}`` mapping back to ``{facet: set}``."""
    if not isinstance(mapping, dict):
        return {}
    out: Dict[str, Set[str]] = {}
    for ftype, vals in mapping.items():
        if isinstance(vals, (list, tuple, set)) and vals:
            out[str(ftype)] = {str(v) for v in vals}
    return out


def serialize_recipe(
    includes: Dict[str, Set[str]],
    excludes: Dict[str, Set[str]],
    rating_range: Tuple[float, float] | None,
    *,
    name: str = "",
) -> Dict[str, Any]:
    """Serialize recipe state to a persistence-friendly ``dict``.

    Args:
        includes: ``{facet_type: set[value]}`` include ingredients.
        excludes: ``{facet_type: set[value]}`` exclude ingredients.
        rating_range: ``(min, max)`` band, or ``None`` for the full span.
        name: Optional display name for the saved recipe.

    Returns:
        A ``dict`` with ``name``, ``includes``, ``excludes`` (facet → sorted
        list) and ``rating_range`` (``[min, max]``) — safe to write to YAML.
    """
    lo, hi = rating_range if rating_range is not None else DEFAULT_RATING_RANGE
    return {
        "name": name,
        "includes": _sets_to_lists(includes),
        "excludes": _sets_to_lists(excludes),
        "rating_range": [float(lo), float(hi)],
    }


def deserialize_recipe(
    data: Dict[str, Any],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Tuple[float, float]]:
    """Deserialize a stored recipe ``dict`` back to live recipe state.

    Missing / malformed fields degrade gracefully: absent includes/excludes
    become empty, and — the backward-compatibility rule — an absent or malformed
    ``rating_range`` becomes the full span :data:`DEFAULT_RATING_RANGE` (no
    rating filter), so recipes saved before the rating axis existed load
    unchanged.

    Args:
        data: A dict previously produced by :func:`serialize_recipe` (or an older
            variant without ``rating_range``).

    Returns:
        ``(includes, excludes, rating_range)`` where includes/excludes are
        ``{facet: set[value]}`` and rating_range is a clamped ``(min, max)``
        tuple.
    """
    includes = _lists_to_sets(data.get("includes"))
    excludes = _lists_to_sets(data.get("excludes"))

    raw = data.get("rating_range")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            lo, hi = float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            lo, hi = DEFAULT_RATING_RANGE
    else:
        lo, hi = DEFAULT_RATING_RANGE

    # Clamp to the scale and order defensively.
    lo = max(RATING_SCALE_MIN, min(lo, RATING_SCALE_MAX))
    hi = max(RATING_SCALE_MIN, min(hi, RATING_SCALE_MAX))
    if lo > hi:
        lo, hi = hi, lo
    return includes, excludes, (lo, hi)

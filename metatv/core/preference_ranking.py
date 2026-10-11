"""Shaping a scored recommendation list — split out of ``preference_engine``.

Scoring decides how much each title fits your taste; these decide how the
top of the list is ASSEMBLED from those scores: averaging a field's matches,
spreading out titles that share a liked person, interleaving movies and series.
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metatv.core.preference_engine import ScoredChannel

# Within-a-single-generation diversity: once a recommendation with a given liked
# performer/director is placed, the NEXT candidate sharing that person is knocked down
# by this factor per prior appearance, so items *without* that person get room to
# surface. It is NOT a stored weight — it only shapes THIS list; engaging with the
# surfaced item (queue / like / dislike) removes it, so the next refresh rotates other
# same-person content back in.
PEOPLE_DIVERSITY_DECAY: float = 0.5

# Only the top slice by score is greedily re-ranked for people-diversity (the tail
# never surfaces) — bounds the O(n²) pass on large libraries.
_DIVERSITY_HEAD: int = 120


def _matched_mean(values) -> float:
    """Mean of the non-neutral (matched) contributions in one attribute field.

    Averaging the *strength* of the affinities an item actually has — rather than
    summing them — stops a big cast list or a long, keyword-dense plot from
    inflating a field by sheer volume. Neutral (0) entries are ignored so they
    don't dilute the average; a matched dislike (negative weight) still pulls the
    field down. Returns 0.0 when nothing matches.
    """
    matched = [v for v in values if v != 0.0]
    return sum(matched) / len(matched) if matched else 0.0


def _diversify_people(scored: list[ScoredChannel],
                      decay: float = PEOPLE_DIVERSITY_DECAY) -> list[ScoredChannel]:
    """Greedily re-rank so the same liked performer/director doesn't fill the list.

    Walks the score-ordered candidates picking, at each step, the highest *effective*
    score — the base score decayed by ``decay`` (default ``PEOPLE_DIVERSITY_DECAY``)
    for each already-placed item that shares one of this candidate's liked people. A
    pure-genre match (no liked people) is never decayed, so it can leapfrog a third
    same-actor title. Only the top ``_DIVERSITY_HEAD`` by score are re-ranked (the
    tail never surfaces); the tail is appended in score order. Input must already be
    sorted by score, descending.
    """
    if len(scored) <= 1:
        return list(scored)
    remaining = list(scored[:_DIVERSITY_HEAD])
    tail = scored[_DIVERSITY_HEAD:]
    out: list[ScoredChannel] = []
    seen: Counter = Counter()
    while remaining:
        best_idx, best_eff = 0, None
        for idx, cand in enumerate(remaining):
            eff = cand.score
            overlap = sum(seen[p] for p in cand.score_people)
            if overlap:
                eff *= decay ** overlap
            if best_eff is None or eff > best_eff:
                best_idx, best_eff = idx, eff
        chosen = remaining.pop(best_idx)
        out.append(chosen)
        for p in chosen.score_people:
            seen[p] += 1
    return out + tail


def _interleave_media_types(scored: list[ScoredChannel], slots: int) -> list[ScoredChannel]:
    """Strict 50/50 round-robin — the legacy ``balance_media_types`` behavior.

    Superseded by ``media_mix`` (see ``metatv.core.media_mix.mix_media_types``),
    which both call sites now use: a fixed half-and-half split ignores that most
    users lean one way. Kept for callers that explicitly ask for an even list.

    Each type keeps its own score order; the type with the stronger top match
    leads. When one type is exhausted the remainder fills from the other. This is
    what keeps the sidebar from filling entirely with movies just because there
    are more of them (or their metadata is richer, inflating raw scores). If only
    one type is present there is nothing to balance — the top ``slots`` are
    returned unchanged.
    """
    if slots <= 0:
        return []
    movies = [s for s in scored if s.media_type == "movie"]
    series = [s for s in scored if s.media_type == "series"]
    if not movies or not series:
        return scored[:slots]
    take_movie = movies[0].score >= series[0].score
    out: list[ScoredChannel] = []
    i = j = 0
    while len(out) < slots and (i < len(movies) or j < len(series)):
        if take_movie and i < len(movies):
            out.append(movies[i])
            i += 1
        elif not take_movie and j < len(series):
            out.append(series[j])
            j += 1
        elif i < len(movies):
            out.append(movies[i])
            i += 1
        else:
            out.append(series[j])
            j += 1
        take_movie = not take_movie
    return out

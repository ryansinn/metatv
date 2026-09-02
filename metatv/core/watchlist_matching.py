"""Does this title match a watch rule? One definition, every surface.

Before this module the answer was open-coded in seven places — two SQL
``ilike('%term%')`` filters in ``repositories/epg.py``, three Python
``pat in title.lower()`` re-checks in the EPG manager, Browse and On Now, and
a substring branch in ``alerts.py`` — all of them plain "contains, anywhere".
That is the enumeration failure this project keeps paying for: a change to one
of them leaves the other six matching differently, and the SQL half decides
what is IN the list while the Python half decides what gets HIGHLIGHTED, so
they drift into disagreeing about the same rule.

Settled in "Catch, Keep, Record" (2026-08-30), Q1:

    Whole word by default, with "contains, anywhere" as the escape hatch.

Whole-word is correctness, not a preference. "NFL" matched *Inflammation* and
*Börsenflash*; "Dragon" matched *Dragonfly*. Those are not near-misses the user
can filter around — the term genuinely is not there.

Two grains, one definition
--------------------------
SQLite ``LIKE`` cannot express a word boundary, so the split is deliberate and
one-directional: :func:`sql_prefilter` returns a **superset** predicate the
database can index, and :func:`matches` makes the real decision in Python.
Every whole-word match is also a substring match, so narrowing in SQL and
deciding in Python loses nothing. The refinement must happen BEFORE any row
limit is applied, which is why :func:`refine` takes the limit rather than
leaving it on the query — see ``EpgRepository.get_upcoming_for_watchlist``.

Slice 1 of WL-1. The rule is a frozen dataclass rather than a bare string
because slice 2 adds ``mode``/``live_only``/``search_description`` and an
``action`` field (Notify / Download / Record), and the artifact's whole point
is that those arrive as fields on this object rather than as a second matcher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class WatchRule:
    """One stored watch rule, as both surfaces see it.

    Attributes:
        term: The include term. A multi-word term is a phrase — "Denver
            Broncos" matches the two words adjacent and in order, which is the
            settled default mode.
        whole_word: Whole-word matching (the default). ``False`` is the
            "contains, anywhere" escape hatch, which is what every rule did
            before this slice.
        exclude: Terms that suppress a match. Governed by the SAME
            ``whole_word`` setting as the include term — one toggle, one
            behaviour, so the row can honestly label itself "Whole words only".
    """

    term: str
    whole_word: bool = True
    exclude: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        """The rule's identity on both surfaces: the term the user typed."""
        return self.term


def matches(text: str, rule: WatchRule) -> bool:
    """True if *text* satisfies *rule* — include term present, no exclude hit.

    An empty term matches NOTHING. ``"" in anything`` is ``True``, which is how
    a blank rule row would otherwise light up every programme in the guide.
    """
    if not text or not rule.term.strip():
        return False

    folded = text.casefold()
    if not _contains(folded, rule.term, rule.whole_word):
        return False
    return not any(_contains(folded, bad, rule.whole_word) for bad in rule.exclude)


def matches_any(text: str, rules: Iterable[WatchRule]) -> bool:
    """True if *text* satisfies at least one rule. The highlight/notify test."""
    return any(matches(text, r) for r in rules)


def matching_rule(text: str, rules: Iterable[WatchRule]) -> WatchRule | None:
    """The first rule *text* satisfies, or None — for "why is this here?" UI."""
    for rule in rules:
        if matches(text, rule):
            return rule
    return None


def refine(
    rows: Sequence[T],
    rule: WatchRule,
    text_of: Callable[[T], str],
    limit: int | None = None,
) -> list[T]:
    """Keep the rows that really match, then apply *limit*.

    The order matters and is the reason this helper exists: applying ``limit``
    in SQL against the coarse prefilter can spend the whole allowance on rows
    the rule rejects, so a real match falls off the end of a list that looks
    full. Refine first, cut second.
    """
    kept = [row for row in rows if matches(text_of(row) or "", rule)]
    return kept[:limit] if limit is not None else kept


def sql_prefilter(column, rule: WatchRule):
    """A SQL predicate matching a SUPERSET of what *rule* accepts.

    Deliberately coarse: ``ilike('%term%')``, the same predicate the watchlist
    queries always used. Word boundaries and exclude terms are applied by
    :func:`matches` afterwards. Never use this as the final answer — it is the
    half that talks to an index, not the half that decides.
    """
    return column.ilike(f"%{_escape_like(rule.term)}%")


def rule_for(term: str) -> WatchRule:
    """A default rule for a bare pattern string — whole-word, no excludes.

    The bridge for call sites that still hold plain strings. It encodes the new
    default, so a caller that has not been migrated to stored rules still gets
    whole-word matching rather than silently keeping the old behaviour.
    """
    return WatchRule(term=term)


def rules_for(terms: Iterable[str]) -> tuple[WatchRule, ...]:
    """:func:`rule_for` over a list of patterns, skipping blanks."""
    return tuple(rule_for(t) for t in terms if (t or "").strip())


def as_rules(items: Iterable[str | WatchRule]) -> tuple[WatchRule, ...]:
    """Normalise a mixed list of terms and rules into rules.

    Lets a query accept the plain ``list[str]`` its existing callers pass while
    a caller holding stored rules passes those instead — one code path either
    way. A bare string is promoted with :func:`rule_for`, so an un-migrated
    caller gets the settled whole-word default rather than quietly keeping the
    old contains-anywhere behaviour.
    """
    out: list[WatchRule] = []
    for item in items:
        if isinstance(item, WatchRule):
            if item.term.strip():
                out.append(item)
        elif (item or "").strip():
            out.append(rule_for(item))
    return tuple(out)


def _contains(folded_text: str, term: str, whole_word: bool) -> bool:
    """Is *term* in *folded_text*, honouring the boundary setting?"""
    needle = (term or "").strip().casefold()
    if not needle:
        return False
    if not whole_word:
        return needle in folded_text
    return _word_re(needle).search(folded_text) is not None


@lru_cache(maxsize=512)
def _word_re(needle_folded: str) -> re.Pattern[str]:
    r"""``(?<!\w)term(?!\w)`` — a boundary that works for a term of any shape.

    ``\b`` is wrong here: it is defined against the character NEXT to it, so
    ``\bF1\b`` behaves one way and ``\b+1\b`` another, and a term beginning or
    ending in punctuation silently stops matching. The lookarounds ask the
    question actually intended — "no word character butts up against this" —
    whatever the term starts and ends with.

    Python's ``\w`` is Unicode-aware on ``str``, so *Börsenflash* excludes
    "NFL" for the same reason *Inflammation* does.
    """
    return re.compile(rf"(?<!\w){re.escape(needle_folded)}(?!\w)")


def _escape_like(term: str) -> str:
    """Neutralise LIKE wildcards in a user's term.

    A rule for "100%" must not become "match anything". The prefilter is only a
    superset, so over-matching here is not a correctness bug — but a term
    containing ``%`` would widen it to the whole table and make the Python pass
    scan the guide.
    """
    return (term or "").replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

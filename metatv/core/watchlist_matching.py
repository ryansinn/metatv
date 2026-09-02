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
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


#: Match modes — how the include terms combine. Settled ("Catch, Keep, Record",
#: the two-axes table): the user's own three names for the same axis, which is
#: one dropdown, not three features.
PHRASE = "phrase"   #: terms adjacent and in order — the default
ALL_WORDS = "all"   #: every term present, anywhere
ANY_WORD = "any"    #: at least one term present
MATCH_MODES = (PHRASE, ALL_WORDS, ANY_WORD)

#: What a rule DOES when it matches. Slice 2 ships the field with only NOTIFY
#: reachable; Download and Record become values here rather than migrations
#: once the transfer engine exists (artifact: "three features, one stored
#: object" — it is only free if the action is a field from the first slice).
NOTIFY = "notify"
DOWNLOAD = "download"
RECORD = "record"
ACTIONS = (NOTIFY, DOWNLOAD, RECORD)


@dataclass(frozen=True)
class WatchRule:
    """One stored watch rule, as both surfaces see it.

    Attributes:
        term: The raw stored include string, and the rule's display identity.
            Comma-separated: "Denver, Broncos, DEN" is three terms combined by
            ``match_mode``. A term containing no comma is one term, which is
            why every existing rule keeps its meaning.
        whole_word: Whole-word matching (the default). ``False`` is the
            "contains, anywhere" escape hatch, which is what every rule did
            before slice 1.
        exclude: Terms that suppress a match. Governed by the SAME
            ``whole_word`` setting as the include terms — one toggle, one
            behaviour, so the row can honestly label itself "Whole words only".
        match_mode: One of :data:`MATCH_MODES`.
        search_description: Look in the programme description as well as the
            title. **Off by default, for old and new rules alike** (Q2): two
            defaults for one setting would mean the checkbox state could never
            be predicted from the setting alone.
        live_only: Match only programmes flagged live. **Not surfaced in the
            UI** — see the note on :func:`matches`; the field exists so the
            rule shape is complete, not because it can be used yet.
        action: One of :data:`ACTIONS`.
    """

    term: str
    whole_word: bool = True
    exclude: tuple[str, ...] = field(default_factory=tuple)
    match_mode: str = PHRASE
    search_description: bool = False
    live_only: bool = False
    action: str = NOTIFY

    @property
    def key(self) -> str:
        """The rule's identity on both surfaces: the string the user typed."""
        return self.term

    @property
    def terms(self) -> tuple[str, ...]:
        """The include terms, split on commas and stripped of blanks.

        Derived rather than stored: ``AlertPatternDB.pattern_value`` stays the
        single string the user typed, so it remains the display label and the
        dict key every surface already looks rules up by. Nothing migrates.
        """
        return tuple(t.strip() for t in (self.term or "").split(",") if t.strip())


def matches(
    text: str,
    rule: WatchRule,
    description: str | None = None,
    is_live: bool | None = None,
) -> bool:
    """True if *text* (and optionally *description*) satisfies *rule*.

    Fields are tested SEPARATELY rather than concatenated. Joining them would
    let a phrase match across the seam — a title ending "Denver" beside a
    description starting "Broncos" is not a programme about the Broncos.

    ``live_only`` is honoured here but is NOT surfaced in the UI: measured on
    the owner's library, ``is_live`` is 0 for all 264,047 programmes, because
    it is only ever set from a superscript ``ᴸᶦᵛᵉ`` badge in the title
    (``xmltv_parser._strip_badges``) and their feeds do not use one. The
    settled design called this "free — the column already exists"; on this data
    a checkbox would silently make every rule match nothing. The field is kept
    so the rule shape is complete and the gate is ready if the column is ever
    populated. ``is_live=None`` means "unknown", which a live-only rule treats
    as not-live.

    An empty term matches NOTHING. ``"" in anything`` is ``True``, which is how
    a blank rule row would otherwise light up every programme in the guide.
    """
    if rule.live_only and not is_live:
        return False

    terms = rule.terms
    if not terms:
        return False

    fields = [text]
    if rule.search_description and description:
        fields.append(description)
    folded = [f.casefold() for f in fields if f]
    if not folded:
        return False

    if not any(_mode_hit(hay, terms, rule) for hay in folded):
        return False
    return not any(_contains(hay, bad, rule.whole_word)
                   for hay in folded for bad in rule.exclude)


def _mode_hit(folded_text: str, terms: tuple[str, ...], rule: WatchRule) -> bool:
    """Combine the include terms the way ``match_mode`` says to."""
    if rule.match_mode == ALL_WORDS:
        return all(_contains(folded_text, t, rule.whole_word) for t in terms)
    if rule.match_mode == ANY_WORD:
        return any(_contains(folded_text, t, rule.whole_word) for t in terms)
    # PHRASE — and anything unrecognised, so a bad stored value degrades to the
    # default rather than matching nothing or everything.
    return _contains(folded_text, " ".join(terms), rule.whole_word)


def matches_any(
    text: str,
    rules: Iterable[WatchRule],
    description: str | None = None,
    is_live: bool | None = None,
) -> bool:
    """True if *text* satisfies at least one rule. The highlight/notify test."""
    return any(matches(text, r, description, is_live) for r in rules)


def matching_rule(
    text: str,
    rules: Iterable[WatchRule],
    description: str | None = None,
    is_live: bool | None = None,
) -> WatchRule | None:
    """The first rule *text* satisfies, or None — for "why is this here?" UI."""
    for rule in rules:
        if matches(text, rule, description, is_live):
            return rule
    return None


def refine(
    rows: Sequence[T],
    rule: WatchRule,
    limit: int | None = None,
) -> list[T]:
    """Keep the programme rows that really match, then apply *limit*.

    The order matters and is the reason this helper exists: applying ``limit``
    in SQL against the coarse prefilter can spend the whole allowance on rows
    the rule rejects, so a real match falls off the end of a list that looks
    full. Refine first, cut second.

    Reads ``title``/``description``/``is_live`` off each row directly rather
    than through ``getattr`` defaults — a row that lacks them is a programming
    error and should say so, not silently match on an empty title.
    """
    kept = [row for row in rows
            if matches(row.title or "", rule, row.description, row.is_live)]
    return kept[:limit] if limit is not None else kept


def sql_prefilter(rule: WatchRule, title_col, description_col=None):
    """A SQL predicate matching a SUPERSET of what *rule* accepts.

    Deliberately coarse — ``ilike('%term%')`` per term — because SQLite cannot
    express a word boundary. Boundaries and exclude terms are applied by
    :func:`matches` afterwards. Never use this as the final answer: it is the
    half that talks to an index, not the half that decides.

    The mode makes it tighter, not just wider. PHRASE and ALL_WORDS both
    require every term, so their prefilter ANDs them — a rule for
    "Denver, Broncos" in phrase mode need never read a row containing only one
    of the two. ANY_WORD is the sole case that has to OR.

    When ``search_description`` is on and a description column is given, each
    term may land in either field, so each term's clause becomes an OR across
    the two. Passing ``description_col=None`` while the rule wants a
    description search is safe: the prefilter then covers titles only, which is
    NARROWER than the rule, so :func:`matches` would never see a
    description-only hit. Callers that support the toggle must pass the column.
    """
    from sqlalchemy import and_, or_

    terms = rule.terms
    if not terms:
        # A blank rule matches nothing; say so in SQL rather than returning a
        # predicate that is trivially true.
        return title_col.is_(None) & title_col.isnot(None)

    def _clause(term: str):
        pattern = f"%{_escape_like(term)}%"
        if rule.search_description and description_col is not None:
            return or_(title_col.ilike(pattern), description_col.ilike(pattern))
        return title_col.ilike(pattern)

    clauses = [_clause(t) for t in terms]
    if len(clauses) == 1:
        return clauses[0]
    return or_(*clauses) if rule.match_mode == ANY_WORD else and_(*clauses)


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
    return _term_re(needle, whole_word).search(folded_text) is not None


@lru_cache(maxsize=1024)
def _term_re(needle_folded: str, whole_word: bool) -> re.Pattern[str]:
    r"""Compile one term (or a joined phrase) into a matcher.

    Internal whitespace becomes ``\s+``, so a phrase survives the double
    spaces and stray tabs real guide titles are full of. That applies to a
    single multi-word term too — "Denver Broncos" and the phrase built from
    "Denver, Broncos" compile identically, which is why the mode dropdown does
    not change what a one-term rule means.

    Whole-word uses lookarounds, not ``\b``. ``\b`` is defined against the
    character NEXT to it, so ``\bF1\b`` behaves one way and ``\b+1\b``
    another, and a term beginning or ending in punctuation silently stops
    matching. The lookarounds ask the intended question — "no word character
    butts up against this" — whatever the term's shape.

    Python's ``\w`` is Unicode-aware on ``str``, so *Börsenflash* excludes
    "NFL" for the same reason *Inflammation* does.
    """
    tokens = needle_folded.split()
    body = r"\s+".join(re.escape(t) for t in tokens) if tokens else re.escape(needle_folded)
    return re.compile(rf"(?<!\w){body}(?!\w)" if whole_word else body)


def _escape_like(term: str) -> str:
    """Neutralise LIKE wildcards in a user's term.

    A rule for "100%" must not become "match anything". The prefilter is only a
    superset, so over-matching here is not a correctness bug — but a term
    containing ``%`` would widen it to the whole table and make the Python pass
    scan the guide.
    """
    return (term or "").replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

"""Fixture OPPONENTS and DISPLAY TITLE out of a sports channel name (SPORT-8).

Its own module for the same reason ``event_datetime.py`` gives its own note:
one cohesive job, and a DIFFERENT grammar from both ``event_datetime.py``
(scheduled time) and ``channel_name_utils.parse_platform_event`` (the
EPG-embedded ``REGION (NETWORK CH#) TITLE (time)`` form). A fixture's window
and its opponents are independent facts read from independent parts of the
same string — merging the two parsers would make neither easier to read.

:func:`fixture_display_title` composes the opponents above into what the
Sports list actually shows ("West Kent Steamers vs Miramichi Timberwolves"
instead of the raw provider slot string) — stored into ``detected_title`` at
the SAME two write sites: ``special_content.update_channel_special_content``
(classification/reclassify) and, so a later provider refresh's prefix pass
doesn't silently overwrite it back to the raw-name parse,
``ChannelIngestionMixin.update_detected_prefixes`` via the
:func:`fixture_ingest_title` wrapper.

Measured on the owner's live corpus, 2026-09-02: 1,237 dated fixtures. The
separator that actually names the two opponents splits as::

    " vs "  765     " @ "  142  (away @ home — see parse_fixture_opponents)
    " x  "   32     " v "    2

The 388 without one of those fall into four shapes, none a plain pair:

* **dash matchup** — two uppercase-dominant team tokens around ``" - "``
  (``"ESBJERG - FREDERIKSHAVN"``). Handled below, gated tightly so an
  ordinary sentence dash (``"EN - Sunny Dancer"``) never matches.
* **racing venue form** — ``"X at Y"`` names an EVENT at a VENUE, not a
  team pair. Nothing here treats "at" as a separator, so this falls
  straight through to ``(None, None)`` — correctly, there is no opponent.
* **single-event races** (``"SPAIN: RACE"``) and **true non-fixtures**
  (``"NHL Tonight"``) — also correctly nothing.

Stored at ingestion by ``special_content.update_channel_special_content``
into ``ChannelDB.event_team_a``/``event_team_b`` (compute once, read
everywhere else) — no consumer calls this function directly.
"""

from __future__ import annotations

import re

from metatv.core.channel_name_utils import FIXTURE_LEAGUE_NAME_PREFIXES

#: A team side must be at least this uppercase to count as a name rather
#: than a sentence fragment — see :func:`_is_uppercase_dominant`.
_UPPERCASE_DOMINANT_THRESHOLD = 0.70

#: Loose gate — does this pipe-segment carry ANY opponent separator at all?
#: Deliberately wide: it only picks which segment to work on. The strict
#: per-form rules live in the ``_try_*`` functions below.
_SEPARATOR_HINT_RE = re.compile(r"\s+(?:vs\.?|x|@|v|-)\s+", re.IGNORECASE)

#: "hockey:  West Kent Steamers vs …" — the FLSP provider's kind label.
_LEADING_LABEL_RE = re.compile(r"^[A-Za-z]+:\s+")

#: Everything from " start:" onward — the MLB slot form's "start:…stop:…"
#: tail, cut in one shot (the stop half sits inside the same tail).
_START_TAIL_RE = re.compile(r"\s+start:.*$", re.IGNORECASE | re.DOTALL)

#: "… _ Field Hockey" — a trailing sport/kind decoration after the title.
_UNDERSCORE_TAIL_RE = re.compile(r"\s+_\s+.+$")

#: A trailing parenthesised timestamp: "(2026-09-02 18:00:00)".
_TIMESTAMP_PAREN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}(?::\d{2})?$")

#: A trailing "(Home)"/"(Away)" annotation.
_HOME_AWAY_RE = re.compile(r"^(?:home|away)$", re.IGNORECASE)

# Priority-ordered split patterns — see step 3 in the module docstring.
_VS_SPLIT_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
_X_SPLIT_RE = re.compile(r"\s+x\s+", re.IGNORECASE)
_AT_SPLIT_RE = re.compile(r"\s+@\s+")
_V_SPLIT_RE = re.compile(r"\s+v\s+", re.IGNORECASE)
_DASH_SPLIT_RE = re.compile(r"\s+-\s+")

#: Edges trimmed off each side after a split. Parens are NOT in here — they
#: are part of real team names ("St. Mary's (MD)").
_EDGE_PUNCT_RE = re.compile(r"^[\s.,;:'\"-]+|[\s.,;:'\"-]+$")


def _select_segment(name: str) -> "str | None":
    """First pipe-segment carrying an opponent separator, or None.

    None is the racing-venue/single-race/non-fixture exit: "at" and a bare
    kind-label colon are not opponent separators.
    """
    for segment in name.split("|"):
        if _SEPARATOR_HINT_RE.search(segment):
            return segment
    return None


def _clean_segment(segment: str) -> str:
    """Strip the leading sport/kind label and collapse doubled spaces."""
    segment = _LEADING_LABEL_RE.sub("", segment.strip(), count=1)
    return re.sub(r"\s+", " ", segment).strip()


def _is_repeat_or_annotation(paren_inner: str) -> bool:
    """A trailing ``(…)`` is schedule noise — timestamp, Home/Away, or a
    REPEAT of the fixture (itself carrying a separator) — never a team name.
    """
    inner = paren_inner.strip()
    return bool(
        _TIMESTAMP_PAREN_RE.match(inner)
        or _HOME_AWAY_RE.match(inner)
        or _SEPARATOR_HINT_RE.search(inner)
    )


def _strip_trailing_paren_group(s: str) -> "tuple[str, str] | None":
    """Split a balanced trailing ``(…)`` off *s*, hand-rolled for nesting.

    "(St. Mary's (MD) vs Batten)" nests one level; ``re`` cannot balance
    parens. Returns ``(remainder, inner_text)``, or None with no trailing
    group (or an unbalanced one — left alone rather than guessed at).
    """
    t = s.rstrip()
    if not t.endswith(")"):
        return None
    depth = 0
    for i in range(len(t) - 1, -1, -1):
        if t[i] == ")":
            depth += 1
        elif t[i] == "(":
            depth -= 1
            if depth == 0:
                return t[:i].rstrip(), t[i + 1:-1]
    return None


def _cut_schedule_tail(working: str) -> str:
    """Cut every trailing schedule/decoration form, looping until stable.

    A timestamp paren and a repeat paren can stack, and removing one can
    reveal a trailing " _ <words>" that was not trailing before — so this
    keeps cutting rather than making one fixed-order pass.
    """
    working = _START_TAIL_RE.sub("", working)
    while True:
        changed = False
        group = _strip_trailing_paren_group(working)
        if group is not None:
            remainder, inner = group
            if _is_repeat_or_annotation(inner):
                working, changed = remainder, True
        m = _UNDERSCORE_TAIL_RE.search(working)
        if m:
            working, changed = working[:m.start()], True
        if not changed:
            return working


def _is_uppercase_dominant(s: str) -> bool:
    """A team NAME reads uppercase-dominant; a sentence fragment does not.

    "EN - Sunny Dancer" must not parse: "Sunny Dancer" is 18% uppercase.
    "PHILLIES" is 100%. No letters at all also fails.
    """
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return (sum(1 for c in letters if c.isupper()) / len(letters)) >= \
        _UPPERCASE_DOMINANT_THRESHOLD


def _try_vs(text: str) -> "tuple[str, str] | None":
    """" vs "/" vs. " — 765 of the 1,237 measured fixtures."""
    m = _VS_SPLIT_RE.search(text)
    return None if m is None else (text[:m.start()].strip(), text[m.end():].strip())


def _try_x(text: str) -> "tuple[str, str] | None":
    """" x " — the MLB slot form, 32 measured. Only when it occurs EXACTLY
    once: a second occurrence leaves no way to tell which is the real one.
    """
    matches = list(_X_SPLIT_RE.finditer(text))
    if len(matches) != 1:
        return None
    left, right = text[:matches[0].start()].strip(), text[matches[0].end():].strip()
    return (left, right) if left and right else None


def _try_at(text: str) -> "tuple[str, str] | None":
    """" @ " — 142 measured, US convention AWAY @ HOME. Returned in the
    order written, ``(away, home)`` — never reordered.
    """
    m = _AT_SPLIT_RE.search(text)
    if m is None:
        return None
    left, right = text[:m.start()].strip(), text[m.end():].strip()
    return (left, right) if left and right else None


def _try_v(text: str) -> "tuple[str, str] | None":
    """" v " — 2 measured. Word-bounded, both sides real names (>=2 chars)."""
    m = _V_SPLIT_RE.search(text)
    if m is None:
        return None
    left, right = text[:m.start()].strip(), text[m.end():].strip()
    return None if len(left) < 2 or len(right) < 2 else (left, right)


def _try_dash(text: str) -> "tuple[str, str] | None":
    """" - " — the dash-matchup shape. Both sides must be uppercase-dominant
    AND 1-4 tokens, so a sentence dash ("EN - Sunny Dancer") never matches.
    """
    m = _DASH_SPLIT_RE.search(text)
    if m is None:
        return None
    left, right = text[:m.start()].strip(), text[m.end():].strip()
    if not (_is_uppercase_dominant(left) and _is_uppercase_dominant(right)):
        return None
    if not (1 <= len(left.split()) <= 4 and 1 <= len(right.split()) <= 4):
        return None
    return _trim_known_league_prefix(left), right


def _trim_known_league_prefix(team_a: str) -> str:
    """Strip a KNOWN spelled-out league name off team A's front.

    "MAJOR LEAGUE BASEBALL DIAMONDBACKS" -> "DIAMONDBACKS". Only a full
    known phrase (:data:`FIXTURE_LEAGUE_NAME_PREFIXES`) is trimmed — an
    unrecognised leading word stays (bias to recall, DR-0006).
    """
    upper = team_a.upper()
    for prefix in FIXTURE_LEAGUE_NAME_PREFIXES:
        if upper == prefix or upper.startswith(prefix + " "):
            return team_a[len(prefix):].strip()
    return team_a


def _parse_fixture_match(name: str) -> "tuple[str, str, bool] | None":
    """Shared engine behind :func:`parse_fixture_opponents` and
    :func:`fixture_display_title` — find the opponent-carrying segment,
    clean it, and try the separators in priority order: ``vs`` > ``x`` >
    ``@`` > ``v`` > the gated dash form. The first that structurally fits
    wins.

    Args:
        name: The raw channel name.

    Returns:
        ``(team_a, team_b, is_at_form)``. ``is_at_form`` is True only for
        the ``@`` AWAY-@-HOME grammar (:func:`_try_at`) — the one shape
        :func:`fixture_display_title` renders as "away at home" rather than
        "a vs b". None when no segment resolves to a pair (a 24/7 rack, a
        single-event race, a racing "X at Y" venue listing, or any name
        whose shape does not confidently resolve).
    """
    if not name:
        return None
    segment = _select_segment(name)
    if segment is None:
        return None

    working = _cut_schedule_tail(_clean_segment(segment))
    is_at_form = False
    sides = _try_vs(working)
    if sides is None:
        sides = _try_x(working)
    if sides is None:
        sides = _try_at(working)
        is_at_form = sides is not None
    if sides is None:
        sides = _try_v(working)
    if sides is None:
        sides = _try_dash(working)
    if sides is None:
        return None

    team_a, team_b = (_EDGE_PUNCT_RE.sub("", s).strip() for s in sides)
    if not team_a or not team_b or team_a.isdigit() or team_b.isdigit():
        return None
    return team_a, team_b, is_at_form


def parse_fixture_opponents(name: str) -> "tuple[str | None, str | None]":
    """The two opponents named in a sports fixture's channel name.

    Pipeline: find the pipe-segment carrying a separator, strip its leading
    kind label, cut every trailing schedule/decoration tail, then try the
    separators in priority order — ``vs`` > ``x`` > ``@`` > ``v`` > the
    gated dash form. The first that structurally fits wins.

    Args:
        name: The raw channel name.

    Returns:
        ``(team_a, team_b)``. For an ``@`` fixture this is ``(away, home)``
        — see :func:`_try_at`. ``(None, None)`` for a 24/7 rack, a
        single-event race, a racing "X at Y" venue listing (no opponent
        exists), or any name whose shape does not confidently resolve.
    """
    match = _parse_fixture_match(name)
    return (None, None) if match is None else match[:2]


def fixture_display_title(name: str) -> "str | None":
    """The fixture's display title — a matchup, or a cleaned single-event name.

    A sports/PPV row's raw ``name`` is a provider slot string, not a title
    ("(FLSP 246) | live: Ireland vs England _ Women's Cricket
    (2026-09-03 08:00:00)"); this derives what should actually be shown.

    Rules:

    * Both opponents resolve (:func:`parse_fixture_opponents`, via the same
      :func:`_parse_fixture_match` engine) -> ``"{team_a} vs {team_b}"`` for
      every grammar except the ``@`` AWAY-@-HOME form, which reads more
      naturally as ``"{away} at {home}"`` — the convention "Lakers @
      Celtics" is spoken as "Lakers at Celtics", not "Lakers vs Celtics".
    * No opponents -> the cleaned single-event segment: the SAME segment
      :func:`_select_segment` would have picked for a pair (so this only
      ever touches a segment that carried a real opponent-separator hint
      and structurally failed to split, e.g. "EN - Sunny Dancer", where
      "Sunny Dancer" is not uppercase-dominant enough to be a team name) —
      cleaned with :func:`_clean_segment` and :func:`_cut_schedule_tail`,
      the exact same two steps :func:`parse_fixture_opponents` applies
      before trying a split. A name with NO separator hint anywhere (a
      single-event race like "SPAIN: RACE", a racing "X at Y" venue
      listing, or an ordinary provider string with no matchup at all, e.g.
      "Rolling Loud") is deliberately left alone here — reusing the SAME
      hint gate that guards the opponent parse is what keeps this from
      grabbing a garbage leading segment ("End") off a PPV row that never
      had a matchup to begin with.
    * Nothing usable survives -> None, meaning "leave detected_title as it
      is" — never an empty/whitespace string.

    Args:
        name: The raw channel name.

    Returns:
        The derived display title, or None.
    """
    if not name:
        return None
    match = _parse_fixture_match(name)
    if match is not None:
        team_a, team_b, is_at_form = match
        return f"{team_a} at {team_b}" if is_at_form else f"{team_a} vs {team_b}"

    segment = _select_segment(name)
    if segment is None:
        return None
    cleaned = _cut_schedule_tail(_clean_segment(segment))
    return cleaned or None


def fixture_ingest_title(channel) -> "str | None":
    """:func:`fixture_display_title`, gated to fixture-classified rows.

    A thin wrapper for ``update_detected_prefixes`` (``channel_ingestion.py``),
    which recomputes ``detected_title`` from the raw name on EVERY provider
    refresh, for EVERY row, whether the name changed or not — a plain
    ``fixture_display_title(channel.name)`` call there would happily derive
    a "matchup" out of an ordinary movie or live channel's name too. Gating
    on ``special_view`` (the SAME condition ``special_content.py`` stores
    opponents under) is what makes it safe to call unconditionally.

    Args:
        channel: A real ``ChannelDB`` row or a duck-typed substitute (the
            sports-reclassify migration's transient scratch instance) with
            ``special_view`` and ``name`` attributes.

    Returns:
        The derived title, or None when the row is not a title-deriving
        fixture — the caller then falls back to its own bare-name parse.
    """
    if getattr(channel, "special_view", None) not in ("sports", "ppv"):
        return None
    return fixture_display_title(getattr(channel, "name", None) or "")

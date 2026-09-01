"""Scheduled start time for a pipe-form sports/PPV event channel name.

Its own module rather than another section of ``channel_name_utils`` — that file
is already 3,393 lines, and this is one cohesive job with one public function.
The project's rule is that a size breach is answered by cohesion rather than
arithmetic, and the single-source-of-truth rule this respects: the timezone
table below exists in exactly one place, and nothing re-derives it.

A DIFFERENT grammar from ``channel_name_utils.parse_platform_event``, which
decodes ``REGION (NETWORK CH#) TITLE (2025-09-03 07:20:00)``. This one decodes
the pipe-delimited PPV/sports form. The two must not be merged: they are two
provider conventions, not two copies of one.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

#: UTC offsets, in MINUTES, for the timezone abbreviations providers actually
#: emit. Measured on the live corpus 2026-08-31 across 555 day-name rows:
#: CEST 301 · EDT 193 · UTC 22 · NDT 20 · EEST 7 · EST 6 · GMT 6. **494 of 555
#: are not GMT**, so a parser that assumes UTC puts 89% of them one to four
#: hours out — and *almost* right is the worst kind of wrong, because nothing
#: looks broken.
#:
#: Abbreviations rather than IANA zones because an abbreviation is what the
#: string carries, and a fixed offset is correct here: the abbreviation already
#: encodes whether DST applies (CET vs CEST, EST vs EDT).
#:
#: Deliberately EXCLUDES the ambiguous ones — ``CST`` is US Central (-6) or
#: China Standard (+8); ``IST`` is India (+5:30) or Irish (+1). Neither appears
#: in the corpus, and guessing an offset is worse than declining to parse.
_EVENT_TZ_OFFSET_MIN: dict[str, int] = {
    "UTC": 0, "GMT": 0, "UT": 0, "Z": 0,
    "WET": 0, "WEST": 60, "BST": 60,
    "CET": 60, "CEST": 120,
    "EET": 120, "EEST": 180, "MSK": 180,
    "AST": -240, "ADT": -180,
    "NST": -210, "NDT": -150,
    "EST": -300, "EDT": -240,
    "MST": -420, "MDT": -360,
    "PST": -480, "PDT": -420,
    "AEST": 600, "AEDT": 660,
}

_EVENT_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"))}
_EVENT_WEEKDAYS = {d: i for i, d in enumerate(
    ("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}

_TZ_SUFFIX = r"(?:\s*\(?\s*([A-Za-z]{1,4})\s*\)?)?"

#: "| 27-08-2026 | 14:00 (GMT) |"  — day-month-year, the only form parsed before.
_EVENT_DMY_RE = re.compile(
    r"\|\s*(\d{2})-(\d{2})-(\d{4})\s*\|\s*(\d{1,2}):(\d{2})" + _TZ_SUFFIX)
#: "| 2026-07-04 | 09:00 (GMT) |" — ISO.
_EVENT_ISO_RE = re.compile(
    r"\|\s*(\d{4})-(\d{2})-(\d{2})\s*\|\s*(\d{1,2}):(\d{2})" + _TZ_SUFFIX)
#: "MLB 04 | Mariners x Red Sox start:2026-08-31 23:45:00 stop:2026-09-01 …"
#: — the provider's event-slot form. NO pipe around the date and NO zone, so
#: neither ISO nor DMY above can see it: both require "| date | time".
#:
#: Measured on the owner's corpus 2026-09-01: 56 rows carry this shape and
#: **not one of them had event_start_time set**, while 4,205 rows in other
#: forms did. That is why the Sports view's "On now" and "Upcoming" lanes were
#: permanently empty and every dated game fell through to "Channels" — with no
#: start time a row cannot be classified live, upcoming OR finished.
#:
#: Read as LOCAL wall-clock, then converted to UTC like every other form here.
#:
#: I first read these as UTC because 23:45/23:05/00:40 are 19:45/19:05/19:40
#: Eastern — textbook MLB starts. That reasoning was clever and WRONG, and it
#: made the feature worse than broken: the owner was watching MLB 04 live while
#: the app filed it under "Finished", because 06:58 UTC had passed even though
#: 06:58 local had not.
#:
#: The only test that decides this is empirical — the game the user is watching
#: RIGHT NOW must classify as on-now — and it says local. A padded slot window
#: (start + ~7h) makes the real-world start time a poor proxy, so do not
#: re-derive the zone from what looks plausible for the sport.
_EVENT_STARTSTOP_IS_LOCAL = True
_EVENT_STARTSTOP_RE = re.compile(
    r"\bstart:\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})")
#: "| Sat 29 Aug 14:00 CEST (DK) |" — day-name, carries a zone and NO YEAR.
_EVENT_DAYNAME_RE = re.compile(
    r"\|\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+"
    r"(\d{1,2}):(\d{2})\s+([A-Za-z]{2,4})")
#: "… (2026-09-03 19:00:25)" — a trailing parenthesised timestamp. 2,843 rows
#: carry it and 842 stored NOTHING, because ``parse_platform_event`` only runs
#: on the 'live_event' branch while 603 of these classify as 'sports'.
_EVENT_PAREN_TS_RE = re.compile(
    r"\(\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::\d{2})?\s*\)")
#: "… @ Aug 27 11:00 AM :Tennis 03" — month-name, 12-hour, NO YEAR and NO
#: weekday to check one against, so the year is the calendar-nearest.
_EVENT_AT_RE = re.compile(
    r"@\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})\s+(\d{1,2}):(\d{2})\s*([AaPp][Mm])")

#: A provider far-future sentinel meaning "always available", not a schedule.
#: Mirrors channel_name_utils._EVENT_SENTINEL_YEAR.
_SENTINEL_YEAR = 2090


def _resolve_year_by_weekday(month: int, day: int, weekday: str,
                             reference: "date") -> Optional[int]:
    """Pick the year that makes *weekday* fall on *month*/*day* near *reference*.

    The day-name form carries no year, so it has to be inferred — but the
    weekday name is a **checksum**, not decoration: only one year in any short
    window puts a given date on a given weekday. Measured over 2025-2027 against
    all 555 day-name rows in the corpus: **555 resolved uniquely, 0 ambiguous,
    0 unmatched.** The year is recovered with certainty rather than guessed.

    Falls back to the calendar-nearest year when the weekday matches nothing,
    which means the provider's own weekday is wrong — the time is still worth
    more than the discarded checksum.
    """
    wd = _EVENT_WEEKDAYS.get(weekday[:3].lower())
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue          # 29 Feb in a non-leap year
        candidates.append(candidate)
    if not candidates:
        return None
    matching = [c for c in candidates if wd is not None and c.weekday() == wd]
    if len(matching) == 1:
        return matching[0].year
    pool = matching or candidates
    return min(pool, key=lambda c: abs((c - reference).days)).year


def _nearest_year(month: int, day: int, reference: "date") -> Optional[int]:
    """Pick the calendar-nearest year for a date carrying no year and no weekday.

    Weaker than :func:`_resolve_year_by_weekday`, and used only for the ``@``
    form, which supplies no weekday to check a candidate against. Nearest-to-
    reference is the honest choice: a schedule string is about the near future
    or recent past, so the wrong year would have to be six months out to win.
    """
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs((c - reference).days)).year


def parse_event_datetime(name: str, *, reference: "Optional[date]" = None
                         ) -> Optional[datetime]:
    """Extract a pipe-form event's scheduled start as a **UTC-naive** datetime.

    Handles all three date shapes the providers emit, and converts from the
    zone named in the string. Returns None when the name carries no date, which
    is the common case — 29,493 of 30,851 sports rows are 24/7 channels with no
    schedule, and that is correct, not a failure.

    Coverage measured on the live corpus 2026-08-31 (1,358 dated rows):

    ==========================  =====  ================================
    form                        rows   before this function
    ==========================  =====  ================================
    ``| 27-08-2026 | 14:00 |``    654   parsed
    ``| Sat 29 Aug 14:00 CEST``   555   **not parsed at all**
    ``| 2026-07-04 | 09:00 |``    149   **not parsed at all**
    ==========================  =====  ================================

    UTC-naive on the way out, matching the ``start_time``/``stop_time``
    convention the EPG layer already enforces (CLAUDE.md: EPG time & timezone).
    An unrecognised or absent zone is treated as UTC, which is what the two
    numeric forms actually say (they carry ``(GMT)``).

    Args:
        name: The raw channel name.
        reference: "Today", for resolving the year-less day-name form. Defaults
            to the current UTC date. Passed in by tests — and used for *every*
            comparison, never re-read from the clock underneath.

    Returns:
        The UTC-naive start, or None when no date is present.
    """
    if not name:
        return None
    if reference is None:
        from metatv.core.epg_utils import now_utc
        reference = now_utc().date()

    tz_name = None
    if (m := _EVENT_STARTSTOP_RE.search(name)) is not None:
        # First: the shape is unambiguous ("start:" + ISO date), and checking it
        # before the pipe forms means a name carrying both cannot be read as the
        # wrong one.
        #
        # These carry NO zone and are local wall-clock (see the pattern's note),
        # so convert to the UTC-naive value the rest of the system stores. The
        # other forms name their zone and are handled by the shared offset below.
        year, month, day, hour, minute = m.groups()
        year, month, day = int(year), int(month), int(day)
        try:
            _local = datetime(year, month, day, int(hour), int(minute))
        except ValueError:
            return None
        return _local.astimezone().astimezone(timezone.utc).replace(tzinfo=None)
    elif (m := _EVENT_DMY_RE.search(name)) is not None:
        day, month, year, hour, minute, tz_name = m.groups()
        year, month, day = int(year), int(month), int(day)
    elif (m := _EVENT_ISO_RE.search(name)) is not None:
        year, month, day, hour, minute, tz_name = m.groups()
        year, month, day = int(year), int(month), int(day)
    elif (m := _EVENT_DAYNAME_RE.search(name)) is not None:
        weekday, day, month_name, hour, minute, tz_name = m.groups()
        month = _EVENT_MONTHS.get(month_name[:3].lower())
        if month is None:
            return None
        day = int(day)
        year = _resolve_year_by_weekday(month, day, weekday, reference)
        if year is None:
            return None
    elif (m := _EVENT_PAREN_TS_RE.search(name)) is not None:
        year, month, day, hour, minute = m.groups()
        year, month, day = int(year), int(month), int(day)
        if year >= _SENTINEL_YEAR:
            return None          # "always available", not a scheduled start
    elif (m := _EVENT_AT_RE.search(name)) is not None:
        month_name, day, hour, minute, meridiem = m.groups()
        month = _EVENT_MONTHS.get(month_name[:3].lower())
        if month is None:
            return None
        day, hour = int(day), int(hour)
        if hour == 12:
            hour = 0
        if meridiem.lower() == "pm":
            hour += 12
        year = _nearest_year(month, day, reference)
        if year is None:
            return None
    else:
        return None

    try:
        local = datetime(year, month, day, int(hour), int(minute))
    except ValueError:
        return None      # 31 Feb, hour 25 — malformed, not parseable

    offset = _EVENT_TZ_OFFSET_MIN.get((tz_name or "").upper(), 0)
    return local - timedelta(minutes=offset)



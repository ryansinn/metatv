"""`PORNBOX` is a platform, and an adult one — it was neither.

Owner report: *"|PORNBOX| is being recorded as a Language, but it's actually a
platform, and a platform that should be flagged as adult at that."*

Both halves were true, and the second was worse than reported: **30 channels,
2 flagged.**

The cause is a lookup-table gap, twice. `PORNBOX` was missing from
`PLATFORM_CODES`, so it fell through to the geographic chip as though it were a
country or a language. And it was missing from `BASE_PREFIX_GROUPS["Adult"]`,
so `is_restricted` — which ships no judgement of its own and reads only that
group — had nothing to match. `is_restricted`'s own docstring already cited the
code: *"real libraries carry codes nobody would guess — one provider uses
PORNBOX."* The code knew; the table did not.

WHY THIS IS NOT A NAME SCAN
---------------------------
Matching stays prefix-scoped. A title containing "XXX" is not adult content:
there is a whole `xXx` action franchise, and `A's to XXX` is a documentary
*about* the industry. A whole-name scan would hide both, and hiding legitimate
content is the expensive direction of this error.

WHY A TABLE FIX IS NOT ENOUGH
-----------------------------
`detected_restricted` is computed at INGESTION and stored, so the table change
does not reach rows already written. `restricted_backfill`'s `CURRENT_VERSION`
goes 1 → 2 to re-sweep them; without that the owner's 30 rows stay unflagged
however correct the table becomes.
"""

from __future__ import annotations

import pytest

from metatv.core.channel_name_utils import PLATFORM_CODES, is_restricted
from metatv.core.config import BASE_PREFIX_GROUPS


def test_pornbox_is_a_platform_not_a_region():
    """THE first half. Without this it renders as a geographic chip."""
    assert "PORNBOX" in PLATFORM_CODES


def test_pornbox_is_adult_by_default():
    """THE second half — 30 channels, 2 flagged, before this."""
    assert "PORNBOX" in BASE_PREFIX_GROUPS["Adult"]
    assert is_restricted("PORNBOX", "|PORNBOX| FAKE TAXI") is True


def test_the_backfill_reruns_so_existing_rows_are_reflagged():
    """A table fix alone leaves every already-ingested row wrong."""
    from metatv.core.migrations.restricted_backfill import CURRENT_VERSION

    assert CURRENT_VERSION >= 2, (
        "detected_restricted is stored at ingestion; without a version bump the "
        "rows already written keep their stale value"
    )


# ── the false positives this must NOT introduce ─────────────────────────────

@pytest.mark.parametrize("prefix,name", [
    ("EN", "xXx"),                            # the Vin Diesel franchise
    ("EN", "xXx: Return of Xander Cage"),
    ("EN", "A's to XXX"),                     # a documentary ABOUT the industry
    ("EN", "EN - XXX Feature"),
    ("EN", "The X Factor"),
    ("EN", "Generation X"),
    ("EN", "Malcolm X"),
])
def test_a_title_containing_xxx_or_x_is_not_adult(prefix, name):
    """Owner's point, kept executable.

    Hiding legitimate content is the expensive direction of this error, which is
    why matching is prefix-scoped and the only name signal ships empty.
    """
    assert is_restricted(prefix, name) is False, (
        f"{name!r} was flagged adult on its title alone"
    )


def test_the_adult_group_still_holds_what_it_did():
    """Adding a code must not drop the ones already there."""
    for code in ("X", "XXX", "ADULT"):
        assert code in BASE_PREFIX_GROUPS["Adult"]


def test_an_adult_prefix_still_matches_case_insensitively():
    assert is_restricted("pornbox", "|pornbox| whatever") is True
    assert is_restricted("PornBox", "|PornBox| whatever") is True


# ── the collection signal ───────────────────────────────────────────────────

def test_an_adult_collection_flags_a_prefix_nobody_curated():
    """The better signal: it needs nobody to have guessed the provider's code.

    On the owner's library "FOR ADULTS" holds 212 channels, 184 already flagged
    by prefix — the other 28 were the PORNBOX ones no table knew about. The
    collection knew.
    """
    assert is_restricted("SOMENEWCODE", "Whatever", None, collection="For Adults") is True


@pytest.mark.parametrize("collection", [
    "FOR ADULTS", "For Adults", "for adults", "  For   Adults  ",
])
def test_the_collection_match_is_case_and_spacing_insensitive(collection):
    assert is_restricted("EN", "T", None, collection=collection) is True


@pytest.mark.parametrize("collection", [
    "Young Adult",          # a legitimate genre — the substring trap
    "Adult Contemporary",   # a music genre
    "Adults in the Room",   # a real 2019 film
    "Drama", "Comedy", None, "",
])
def test_a_collection_merely_containing_adult_is_not_flagged(collection):
    """Exact match, never substring.

    Owner: "just because there is 'Adult' in a category or collection doesn't
    mean it's an adult collection". Measured on the library: of 1,909 distinct
    collections exactly ONE contains the word, and it is unambiguous — but the
    matching rule has to be right for the libraries this has not seen.
    """
    assert is_restricted("EN", "A Title", None, collection=collection) is False


def test_the_curated_set_is_exact_labels_not_patterns():
    """A pattern would re-introduce the substring problem by the back door."""
    from metatv.core.channel_name_utils import ADULT_COLLECTION_LABELS

    for label in ADULT_COLLECTION_LABELS:
        assert label == label.strip().upper(), f"{label!r} is not normalised"
        assert "*" not in label and "%" not in label, f"{label!r} looks like a pattern"


def test_ingestion_passes_the_collection_it_already_computed():
    """Derived: the signal is worthless if the call site does not pass it."""
    import ast
    import pathlib

    src = pathlib.Path("metatv/core/repositories/channel_ingestion.py").read_text()
    call = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "is_restricted"
    )
    assert any(kw.arg == "collection" for kw in call.keywords), (
        "ingestion computes new_collection and then calls is_restricted without it"
    )

"""A collapsed title must not die with its representative.

Owner's report: an Aladdin they had just been shown "doesn't seem to appear at
all". It had 15 variants. Collapse elects ONE representative per title inside
SQL, ranked by quality then id — and Global Exclusions are applied in Python
*after* that. The winner was `|DE| Aladdin 4K`; `DE` is an excluded prefix; the
representative was dropped and the whole title went with it, including three
variants the owner had never excluded.

Measured on the real 492k-channel library: **18,486 titles** disappeared this
way, each with at least one visible variant. `tmdb:693134` had 47 rows, 9 of
them visible, and rendered nothing.

``get_all``'s own docstring already states the invariant for the provider axis
— "a hidden/expired-provider variant can never be excluded-from-set-yet-still-
win the representative slot" — because that axis is a WHERE predicate. The
Global-Exclusion axes are applied in Python, so they needed the same guarantee
by another route: they now RANK the election.

Ranking, not filtering. Filtering would elect nothing for a fully-excluded
group (right outcome) but would also change ``_variant_count`` (the ×N badge)
and zero the caller's hidden-by-exclusions diff, which is computed by comparing
row counts either side of its Python pass.

These use a REAL Database on a tmp_path file, per CLAUDE.md — the behaviour is
a SQL window function, and a mock would simply agree with whatever it was told.
"""

from __future__ import annotations

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.filter_utils import is_channel_excluded
from metatv.core.repositories.channel import ChannelRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(f"sqlite:///{tmp_path/'t.db'}")
    db.create_tables()
    with db.session_scope() as session:
        yield ChannelRepository(session), session


def _add(session, cid, *, key, quality=None, prefix=None, region=None,
         name=None, user_category=None):
    session.add(ChannelDB(
        id=cid, name=name or cid, content_key=key, media_type="movie",
        detected_quality=quality, detected_prefix=prefix, detected_region=region,
        detected_title="T", provider_id="p1", source_id="s1", user_category=user_category,
        category="",
    ))


def _collapse(repo, session, **sets):
    q = session.query(ChannelDB)
    return repo._get_all_collapsed(q, limit=50, offset=None, exclusion_sets=sets or None)


def test_the_reported_bug_the_best_variant_is_excluded(repo):
    """Kraven-shaped: the 4K copy is excluded, a visible 4K copy exists."""
    r, session = repo
    _add(session, "de4k", key="k", quality="4K", prefix="DE", name="|DE| A 4K")
    _add(session, "multi4k", key="k", quality="4K", prefix="MULTI", name="|MULTI| A 4K")
    _add(session, "en", key="k", prefix="EN", name="|EN| A")
    session.flush()

    excluded = {"DE"}
    reps = _collapse(r, session, excluded_prefixes=excluded)
    assert len(reps) == 1
    rep = reps[0]

    assert not is_channel_excluded(rep.detected_prefix, rep.detected_region, excluded), (
        f"the representative is {rep.detected_prefix!r}, which is excluded — "
        f"the caller will drop it and the whole title disappears"
    )
    assert rep.id == "multi4k", "should elect the best VISIBLE variant"


def test_without_the_ranking_the_title_would_die(repo):
    """The pre-fix behaviour, asserted, so the test cannot silently stop mattering."""
    r, session = repo
    _add(session, "de4k", key="k", quality="4K", prefix="DE")
    _add(session, "multi4k", key="k", quality="4K", prefix="MULTI")
    session.flush()

    rep = _collapse(r, session)[0]          # no exclusion sets — old behaviour
    assert rep.id == "de4k", (
        "quality-then-id ranking should still pick the DE row when nothing is "
        "deprioritised; if this changed, the fix below proves nothing"
    )


def test_quality_still_decides_among_visible_variants(repo):
    """Deprioritising must not become the only thing that matters."""
    r, session = repo
    _add(session, "sd", key="k", quality="SD", prefix="EN")
    _add(session, "uhd", key="k", quality="4K", prefix="EN")
    session.flush()

    rep = _collapse(r, session, excluded_prefixes={"DE"})[0]
    assert rep.id == "uhd", "the best visible quality must still win"


def test_a_fully_excluded_title_still_elects_a_representative(repo):
    """So the caller's Python pass can drop it — and the count stays honest.

    Filtering here instead would make the group vanish silently from the SQL,
    and the caller's hidden-by-exclusions diff would read zero: the gold bar
    would stop reporting content it is still hiding.
    """
    r, session = repo
    _add(session, "de1", key="k", quality="4K", prefix="DE")
    _add(session, "nl1", key="k", prefix="NL")
    session.flush()

    reps = _collapse(r, session, excluded_prefixes={"DE", "NL"})
    assert len(reps) == 1, "a fully-excluded group must still produce a row to drop"
    assert is_channel_excluded(
        reps[0].detected_prefix, reps[0].detected_region, {"DE", "NL"}
    )


def test_the_variant_count_is_unchanged_by_ranking(repo):
    """The ×N badge counts variants, not survivors — ranking must not filter."""
    r, session = repo
    for i in range(5):
        _add(session, f"de{i}", key="k", prefix="DE")
    _add(session, "en", key="k", prefix="EN")
    session.flush()

    rep = _collapse(r, session, excluded_prefixes={"DE"})[0]
    assert rep._variant_count == 6, (
        f"variant count is {rep._variant_count}, expected 6 — the ranking "
        f"filtered rows out instead of just reordering them"
    )


def test_no_cartesian_product(repo):
    """The clause must be built against the SUBQUERY, not the mapped class.

    Built against ChannelDB it adds `channels` as a second FROM element and
    SQLite answers with a cross join — which it did, reporting a variant count
    of 7,386,000 for a 15-row group.
    """
    r, session = repo
    for i in range(4):
        _add(session, f"c{i}", key="k", prefix="DE" if i else "EN")
    session.flush()

    rep = _collapse(r, session, excluded_prefixes={"DE"})[0]
    assert rep._variant_count == 4, (
        f"variant count {rep._variant_count} — a cross join has multiplied the rows"
    )


def test_the_user_category_axis_deprioritises_too(repo):
    r, session = repo
    _add(session, "trash", key="k", quality="4K", user_category="Trash", prefix="EN")
    _add(session, "keep", key="k", prefix="EN")
    session.flush()

    rep = _collapse(r, session, excluded_user_categories={"Trash"})[0]
    assert rep.id == "keep"


def test_the_channel_id_axis_deprioritises_too(repo):
    """The content-type tag layer, pre-resolved to ids by the caller."""
    r, session = repo
    _add(session, "ai", key="k", quality="4K", prefix="EN")
    _add(session, "human", key="k", prefix="EN")
    session.flush()

    rep = _collapse(r, session, excluded_channel_ids={"ai"})[0]
    assert rep.id == "human"


def test_nothing_excluded_leaves_the_ranking_exactly_as_it_was(repo):
    """No exclusions → no rank term at all, so no behaviour change for anyone."""
    r, session = repo
    _add(session, "a", key="k", quality="4K")
    _add(session, "b", key="k")
    session.flush()

    assert _collapse(r, session)[0].id == "a"
    assert _collapse(r, session, excluded_prefixes=set())[0].id == "a"


def test_groups_are_independent(repo):
    """Deprioritising in one title must not reorder another."""
    r, session = repo
    _add(session, "k1_de", key="k1", quality="4K", prefix="DE")
    _add(session, "k1_en", key="k1", prefix="EN")
    _add(session, "k2_en4k", key="k2", quality="4K", prefix="EN")
    _add(session, "k2_ensd", key="k2", quality="SD", prefix="EN")
    session.flush()

    reps = {r_.content_key: r_.id for r_ in _collapse(r, session, excluded_prefixes={"DE"})}
    assert reps == {"k1": "k1_en", "k2": "k2_en4k"}


# ── Tier 1: visible, but region-tainted ──────────────────────────────────────

def test_a_visible_copy_from_an_excluded_region_is_not_put_forward(repo):
    """The owner's observation, and it is not the same question as visibility.

    ``is_channel_excluded`` says "language wins over region": a row with an
    explicit un-excluded prefix stays VISIBLE even when its region is excluded,
    because excluding German must not hide an English film merely filed under a
    German category. That rule is right.

    Election is a different question. The real case: ``aladdin|movie|`` elected
    ``|MULTI| Aladdin 4K`` (prefix MULTI, region DE) while ``|EN| Aladdin 4K``
    sat beside it at the same quality carrying no excluded code at all — so the
    German Disney copy represented the title to someone who excludes German.
    """
    r, session = repo
    _add(session, "multi_de", key="k", quality="4K", prefix="MULTI", region="DE")
    _add(session, "en", key="k", quality="4K", prefix="EN")
    session.flush()

    rep = _collapse(r, session, excluded_prefixes={"DE"})[0]
    assert rep.id == "en", (
        "elected the MULTI/DE copy over an equal-quality copy with no excluded "
        "code on it — the German copy represents the title to someone who "
        "excludes German"
    )


def test_a_region_tainted_copy_still_wins_when_it_is_the_only_one(repo):
    """Tier 1 demotes; it must never hide.

    The row is visible by the exclusion rule and stays visible — losing the
    slot to nothing would be the vanishing bug all over again.
    """
    r, session = repo
    _add(session, "multi_de", key="k", prefix="MULTI", region="DE")
    _add(session, "de", key="k", quality="4K", prefix="DE")
    session.flush()

    reps = _collapse(r, session, excluded_prefixes={"DE"})
    assert len(reps) == 1
    assert reps[0].id == "multi_de", (
        "the only visible copy must still be elected, even region-tainted, "
        "and even though the excluded copy has better quality"
    )


def test_region_taint_outranks_quality_but_exclusion_outranks_both(repo):
    """The three tiers, in order, in one group."""
    r, session = repo
    _add(session, "excluded_4k", key="k", quality="4K", prefix="DE")
    _add(session, "tainted_4k", key="k", quality="4K", prefix="MULTI", region="DE")
    _add(session, "clean_sd", key="k", quality="SD", prefix="EN")
    session.flush()

    rep = _collapse(r, session, excluded_prefixes={"DE"})[0]
    assert rep.id == "clean_sd", (
        "a clean SD copy should out-rank a region-tainted 4K one — putting a "
        "compromised copy forward is worse than putting a lower-quality one"
    )


def test_taint_only_applies_to_codes_the_user_actually_excluded(repo):
    """A region is not a problem in itself."""
    r, session = repo
    _add(session, "multi_de", key="k", quality="4K", prefix="MULTI", region="DE")
    _add(session, "en", key="k", prefix="EN")
    session.flush()

    rep = _collapse(r, session, excluded_prefixes={"NL"})[0]
    assert rep.id == "multi_de", (
        "DE is not excluded here, so the 4K copy should win on quality as usual"
    )

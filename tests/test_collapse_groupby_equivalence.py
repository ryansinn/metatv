"""The collapse elects by rank and orders by the REPRESENTATIVE's name.

Collapsing variants cost **8.34 s** per channel-list load on the owner's
library against 0.04 s with it off, and it was LIMIT-independent — asking for
100 rows cost the same as 1,000 — because `ROW_NUMBER()` has to number every
row before the ones numbered 1 can be kept. Grouping collapses each title as it
scans instead: **8.34 s → 1.63 s**, verified byte-identical against the old
implementation across six page and filter combinations on the real library.

Two things in that rewrite can break silently, and both are covered here.

**The packing.** `ORDER BY penalty, rank, id` and `MIN(penalty || rank || id)`
agree only while penalty and rank are FIXED WIDTH. A two-digit rank sorts before
a one-digit one, so adding a quality tier would re-elect every representative in
the library with nothing failing. The widths are derived from the actual ranges;
these tests drive a widened ladder to prove the derivation holds.

**The ordering.** The grouped query holds only aggregates, so the obvious way to
get a name to sort by is `MIN(name)` — which is the alphabetically first name in
the GROUP, a different row from the one elected. That is why there is a join
back. `test_ordering_follows_the_representative_not_the_group` is built so those
two answers disagree, and fails against the aggregate shortcut.
"""

from __future__ import annotations

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories.channel import ChannelRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'collapse.db'}")
    db.create_tables()
    with db.session_scope() as session:
        yield ChannelRepository(session), session
    db.close()


def _add(session, cid, *, key, quality=None, name=None, prefix=None, region=None):
    session.add(ChannelDB(
        id=cid, name=name or cid, content_key=key, media_type="movie",
        detected_quality=quality, detected_prefix=prefix, detected_region=region,
        detected_title="T", provider_id="p1", source_id="s1", category="",
    ))


def _collapse(repo, session, *, limit=50, offset=None, **sets):
    return repo._get_all_collapsed(
        session.query(ChannelDB), limit=limit, offset=offset,
        exclusion_sets=sets or None,
    )


# ── the ordering trap ───────────────────────────────────────────────────────

def test_ordering_follows_the_representative_not_the_group(repo):
    """THE assertion this rewrite could have got wrong.

    Two titles. In each, the elected representative's name sorts the OPPOSITE
    way from the group's alphabetically-first name — so ordering by ``MIN(name)``
    puts them in the other order. Only the representative's own name gives the
    order the uncollapsed list uses.

        group 1   rep "Zulu 4K"   also holds "Alpha SD"
        group 2   rep "Mambo 4K"  also holds "Bravo SD"

      by representative : Mambo 4K, Zulu 4K
      by MIN(name)      : Alpha SD -> group 1 first, i.e. the reverse
    """
    r, session = repo
    _add(session, "g1rep", key="k1", quality="4K", name="Zulu 4K")
    _add(session, "g1alt", key="k1", quality="SD", name="Alpha SD")
    _add(session, "g2rep", key="k2", quality="4K", name="Mambo 4K")
    _add(session, "g2alt", key="k2", quality="SD", name="Bravo SD")
    session.flush()

    reps = _collapse(r, session)

    assert [c.id for c in reps] == ["g2rep", "g1rep"], (
        "ordered by the group's first name rather than the representative's — "
        f"got {[c.name for c in reps]}"
    )


# ── election ────────────────────────────────────────────────────────────────

def test_the_best_quality_variant_represents_the_title(repo):
    r, session = repo
    _add(session, "sd", key="k", quality="SD", name="A SD")
    _add(session, "uhd", key="k", quality="4K", name="A 4K")
    _add(session, "hd", key="k", quality="HD", name="A HD")
    session.flush()

    reps = _collapse(r, session)

    assert [c.id for c in reps] == ["uhd"]
    assert reps[0]._variant_count == 3


def test_id_breaks_a_quality_tie_the_same_way_order_by_would(repo):
    """``MIN(prefix || id)`` must tie-break exactly as ``ORDER BY …, id``."""
    r, session = repo
    for cid in ("zzz", "aaa", "mmm"):
        _add(session, cid, key="k", quality="HD", name=f"A {cid}")
    session.flush()

    reps = _collapse(r, session)

    assert [c.id for c in reps] == ["aaa"], "the lowest id must win a tie"


def test_an_ungrouped_row_is_its_own_group(repo):
    """A NULL content_key falls back to ``id:<id>`` — one title, one row."""
    r, session = repo
    _add(session, "lonely", key=None, quality="HD", name="Solo")
    _add(session, "pair_a", key="k", quality="HD", name="Duo A")
    _add(session, "pair_b", key="k", quality="SD", name="Duo B")
    session.flush()

    reps = _collapse(r, session)

    assert sorted(c.id for c in reps) == ["lonely", "pair_a"]
    assert {c.id: c._variant_count for c in reps} == {"lonely": 1, "pair_a": 2}


# ── the packing width ───────────────────────────────────────────────────────

def test_a_wider_quality_ladder_still_elects_correctly(repo, monkeypatch):
    """Drive a two-digit rank. A hardcoded width would re-elect everything.

    The failure this guards is silent: with a fixed one-digit prefix, rank 10
    packs as "10…" and sorts BEFORE rank 2's "2…", so the worst copy in the
    library becomes the representative and nothing raises.
    """
    from metatv.core import channel_name_utils
    from metatv.core.repositories import channel as channel_mod

    # Chosen so the WRONG width flips the winner, which a merely-wide ladder
    # does not. The sort rank is ``max_tier - tier``, so:
    #
    #   BETTER  tier 10 -> rank  2      correct width 2 -> "02"
    #   WORSE   tier  2 -> rank 10                        -> "10"
    #
    # "02" < "10", so BETTER is elected. With a hardcoded width of 1 they pack
    # as "2" and "10", and "10" < "2" lexicographically — the WORSE copy wins,
    # silently, with nothing raising.
    wide = dict(channel_name_utils.QUALITY_TIER_RANK)
    wide.update({"TOPTIER": 12, "BETTER": 10, "WORSE": 2})
    monkeypatch.setattr(channel_name_utils, "QUALITY_TIER_RANK", wide)
    monkeypatch.setattr(channel_mod, "QUALITY_TIER_RANK", wide, raising=False)
    monkeypatch.setattr(channel_mod, "_MAX_QUALITY_RANK", max(wide.values()))

    r, session = repo
    _add(session, "best", key="k", quality="BETTER", name="A better")
    _add(session, "worst", key="k", quality="WORSE", name="A worse")
    session.flush()

    reps = _collapse(r, session)

    assert [c.id for c in reps] == ["best"], (
        "a two-digit rank re-elected the wrong copy — the packing width is "
        "hardcoded somewhere instead of derived"
    )


def test_the_max_rank_is_read_from_the_lookup_table(repo):
    """Derived, not written down beside it."""
    from metatv.core.channel_name_utils import QUALITY_TIER_RANK
    from metatv.core.repositories.channel import _MAX_QUALITY_RANK

    assert _MAX_QUALITY_RANK == max(QUALITY_TIER_RANK.values())


# ── pagination ──────────────────────────────────────────────────────────────

def test_pages_do_not_overlap_or_skip(repo):
    """LIMIT/OFFSET apply to GROUPS, and a page boundary must be stable."""
    r, session = repo
    for i in range(30):
        _add(session, f"a{i:02d}", key=f"k{i:02d}", quality="HD", name=f"Title {i:02d}")
        _add(session, f"b{i:02d}", key=f"k{i:02d}", quality="SD", name=f"Title {i:02d} alt")
    session.flush()

    whole = [c.id for c in _collapse(r, session, limit=100)]
    paged = []
    for off in range(0, 30, 7):
        paged += [c.id for c in _collapse(r, session, limit=7, offset=off)]

    assert len(whole) == 30, "one row per title, not per variant"
    assert paged == whole, "paging duplicated or skipped a group"


def test_asking_for_one_page_returns_one_page(repo):
    r, session = repo
    for i in range(20):
        _add(session, f"c{i:02d}", key=f"g{i:02d}", quality="HD", name=f"N {i:02d}")
    session.flush()

    assert len(_collapse(r, session, limit=5)) == 5


def test_an_empty_library_collapses_to_nothing(repo):
    r, session = repo
    assert _collapse(r, session) == []

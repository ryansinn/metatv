"""A facet filter may reject a VALUE; it may not reject an absence (#298).

The bug, in the owner's words
----------------------------
    "There are means to exclude Always Sunny — by unselecting English, or
    Comedy, or Decade 2000s. So it's not like it can't be excluded, it's just
    being excluded (along with a bunch of other content) by default for no good
    reason or intentional reason."

    "If absolutely EVERY filter is selected in Search — which is the implication
    that EVERYTHING should be included — then to have a portion of results
    excluded because the available filters are insufficient to represent them
    is the issue."

What was wrong
--------------
Each ticked facet compiled to a bare ``EXISTS(tag of this type IN (ticked))``,
which cannot distinguish "carries a value you unticked" from "carries no value
on this facet at all". Because the tag corpus is SPARSE on purpose — the
decomposer records what a feeder actually denotes and invents nothing — most
channels have nothing on most facets, so a partially-ticked section culled the
library rather than narrowing it.

Measured on the owner's real 489,954-channel library, survivors when a single
facet filter was switched on:

    facet      before        after
    dub            12      489,952
    subtitle    1,834      489,088
    format      2,952      489,954
    category    5,488      489,687
    quality    31,378      489,954
    platform   38,347      489,856
    genre     129,995      489,363

Unticking one subtitle language did not remove that language; it removed the
99.6% of the library never tagged for subtitles. That is a suppression gate
built out of missing guesses, which CLAUDE.md's tags rule forbids in as many
words ("confidence is ranking/prune-priority, never a suppression gate") and
which the mirror-not-cage tenet exists to prevent.

Every test below fails against the pre-#298 predicate.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory

FACETS = ["language", "region", "genre", "quality", "platform",
          "subtitle", "dub", "format", "category"]


@pytest.fixture
def session(tmp_path: Path):
    """File-backed DB (CLAUDE.md: never :memory: for session work)."""
    db = Database(f"sqlite:///{tmp_path / 'facets.db'}")
    db.create_tables()
    s = db.get_session()
    yield s
    s.close()
    db.close()


def _ch(session, name: str, media_type: str = "series") -> str:
    ch = ChannelDB(id=str(uuid.uuid4()), source_id=str(uuid.uuid4()),
                   provider_id="p1", name=name, media_type=media_type, is_hidden=False)
    session.add(ch)
    session.flush()
    return ch.id


def _tag(repos, channel_id: str, *pairs: tuple[str, str]) -> None:
    repos.tags.set_content_tags(channel_id, [(t, v, "test_feeder") for t, v in pairs])


def _sunny(session, repos) -> str:
    """The reported channel, tagged exactly as it is in the owner's library:
    ``EN - It's Always Sunny In Philadelphia (2005)`` carries collection,
    decade, genre and language — and nothing on the other five facets."""
    cid = _ch(session, "EN - It's Always Sunny In Philadelphia (2005)")
    _tag(repos, cid,
         ("collection", "Comedy Series"), ("decade", "2000s"),
         ("genre", "Comedy"), ("language", "English"))
    return cid


# ---------------------------------------------------------------------------
# The reported case
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("facet,ticked", [
    ("subtitle", {"English", "Multi"}),
    ("dub", {"English"}),
    ("region", {"US", "UK"}),
    ("platform", {"Netflix", "Disney+"}),
    ("category", {"Sports", "News"}),
    ("quality", {"HD", "SD"}),
    ("format", {"Dub", "Sub"}),
])
def test_a_facet_it_carries_no_tag_for_cannot_hide_it(session, facet, ticked):
    """It has no tag on any of these facets, so none of them may reject it.

    PRE-#298 EVERY PARAMETRISATION FAILED: the channel was dropped by all seven.
    """
    repos = RepositoryFactory(session)
    cid = _sunny(session, repos)
    session.commit()

    rows = repos.channels.get_all(tag_includes={facet: ticked})
    assert cid in {r.id for r in rows}, (
        f"hidden by the {facet} filter despite carrying no {facet} tag at all"
    )


def test_every_facet_at_once_still_leaves_it_visible(session):
    """The real filter panel constrains several facets simultaneously."""
    repos = RepositoryFactory(session)
    cid = _sunny(session, repos)
    session.commit()

    rows = repos.channels.get_all(tag_includes={
        "language": {"English"}, "genre": {"Comedy"},
        "subtitle": {"English"}, "dub": {"English"}, "region": {"US"},
        "platform": {"Netflix"}, "category": {"Sports"},
        "quality": {"HD"}, "format": {"Dub"},
    })
    assert cid in {r.id for r in rows}


# ---------------------------------------------------------------------------
# The other half — it must still be excludable, deliberately
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("facet,ticked", [
    ("genre", {"Drama", "Horror"}),        # it IS Comedy
    ("language", {"Spanish", "German"}),   # it IS English
    ("collection", {"Drama Series"}),      # it IS Comedy Series
    ("decade", {"1990s"}),                 # it IS 2000s
])
def test_unticking_a_value_it_actually_carries_still_hides_it(session, facet, ticked):
    """The owner's own framing of where the line sits: "there are means to
    exclude it — by unselecting English, or Comedy, or Decade 2000s".

    Without this, "be more inclusive" would have quietly become "the filters
    do nothing", which is the failure mode on the other side of this change.
    """
    repos = RepositoryFactory(session)
    cid = _sunny(session, repos)
    session.commit()

    rows = repos.channels.get_all(tag_includes={facet: ticked})
    assert cid not in {r.id for r in rows}, (
        f"{facet}={ticked} excludes a value this channel actually carries — it "
        f"must still be hidden"
    )


def test_a_rival_value_is_rejected_while_an_absence_is_not(session):
    """Both halves of the rule in one query — the distinction the old bare
    EXISTS could not express."""
    repos = RepositoryFactory(session)
    carries_wrong = _ch(session, "Netflix Show")
    carries_right = _ch(session, "Disney Show")
    carries_none = _ch(session, "Plain Show")
    _tag(repos, carries_wrong, ("platform", "Netflix"))
    _tag(repos, carries_right, ("platform", "Disney+"))
    _tag(repos, carries_none, ("genre", "Comedy"))
    session.commit()

    ids = {r.id for r in repos.channels.get_all(tag_includes={"platform": {"Disney+"}})}
    assert carries_right in ids, "the ticked value passes"
    assert carries_none in ids, "an absence is not a rejection"
    assert carries_wrong not in ids, "an unticked value is still a rejection"


# ---------------------------------------------------------------------------
# Scale — the property that made this a library-wide cull rather than a nit
# ---------------------------------------------------------------------------

def test_a_sparse_facet_no_longer_culls_the_library(session):
    """One tagged channel and 50 untagged ones: filtering on the sparse facet
    used to return 1. It must now return 51.

    This is the shape of the real defect — the owner's dub facet had 14 tagged
    channels out of 489,954, so switching it on returned 12 rows.
    """
    repos = RepositoryFactory(session)
    tagged = _ch(session, "Has A Dub Tag")
    _tag(repos, tagged, ("dub", "English"))
    untagged = [_ch(session, f"No Dub Tag {i}") for i in range(50)]
    for cid in untagged:
        _tag(repos, cid, ("genre", "Comedy"))
    session.commit()

    ids = {r.id for r in repos.channels.get_all(tag_includes={"dub": {"English"}})}
    assert tagged in ids
    assert len(ids) == 51, (
        f"a sparse facet still culls the library: {len(ids)} of 51 survived"
    )


def test_context_chip_stays_strict(session):
    """The details-pane metadata chip means "show me ONLY this" — an explicit,
    ephemeral, one-tag request, not a vocabulary the user is narrowing. It must
    NOT inherit the inclusive rule (docs/CONTEXT_FILTER_CHIPS.md)."""
    repos = RepositoryFactory(session)
    cid = _sunny(session, repos)
    other = _ch(session, "Untagged Thing")
    _tag(repos, other, ("language", "English"))
    session.commit()

    ids = {r.id for r in repos.channels.get_all(context_tag_filter=("genre", "Comedy"))}
    assert cid in ids, "the channel genuinely tagged Comedy is shown"
    assert other not in ids, (
        "a channel with no genre tag must NOT appear under an explicit "
        "'show me only Comedy' chip"
    )


# ---------------------------------------------------------------------------
# The opt-in strict mode — the "Untagged" footer row switched OFF
# ---------------------------------------------------------------------------

class TestUntaggedOptOut:
    """Unticking a section's "Untagged" row restores the strict behaviour for
    that ONE facet, without touching any other.

    This is what makes the inclusive default safe to ship: nothing is taken
    away, the strict form just stops being the silent default.
    """

    def test_hiding_untagged_excludes_it_again(self, session):
        repos = RepositoryFactory(session)
        cid = _sunny(session, repos)
        session.commit()

        visible = repos.channels.get_all(tag_includes={"subtitle": {"English"}})
        assert cid in {r.id for r in visible}, "default is inclusive"

        strict = repos.channels.get_all(
            tag_includes={"subtitle": {"English"}},
            facets_hiding_untagged={"subtitle"},
        )
        assert cid not in {r.id for r in strict}, (
            "with the untagged row unticked, only titles carrying a subtitle "
            "value may pass"
        )

    def test_opting_out_of_one_facet_does_not_affect_another(self, session):
        """Per-facet, not global — the reason this is a row inside each section
        rather than one switch somewhere else."""
        repos = RepositoryFactory(session)
        cid = _sunny(session, repos)
        session.commit()

        rows = repos.channels.get_all(
            tag_includes={"subtitle": {"English"}, "platform": {"Netflix"}},
            facets_hiding_untagged={"platform"},
        )
        assert cid not in {r.id for r in rows}, "platform strictness still applies"

        rows = repos.channels.get_all(
            tag_includes={"subtitle": {"English"}, "platform": {"Netflix"}},
            facets_hiding_untagged=set(),
        )
        assert cid in {r.id for r in rows}, "neither facet is strict here"

    def test_a_tagged_channel_is_unaffected_by_the_opt_out(self, session):
        """The switch only decides what happens to ABSENCE; a channel carrying a
        ticked value passes either way."""
        repos = RepositoryFactory(session)
        cid = _ch(session, "Has Subtitles")
        _tag(repos, cid, ("subtitle", "English"))
        session.commit()

        for strict in (set(), {"subtitle"}):
            rows = repos.channels.get_all(
                tag_includes={"subtitle": {"English"}}, facets_hiding_untagged=strict)
            assert cid in {r.id for r in rows}, f"strict={strict!r} must not affect it"


# ---------------------------------------------------------------------------
# The count behind the footer row — EXECUTED, not faked
# ---------------------------------------------------------------------------

class TestUntaggedCounts:
    """``get_facet_untagged_counts`` must actually RUN.

    It shipped broken: the query joined ``ChannelDB`` to itself and raised
    ``InvalidRequestError: Don't know how to join to ChannelDB``. Nothing went
    red, because the only test covering the path used a fake tag repository and
    so never executed a line of SQL — a green shape test in exactly the sense
    CLAUDE.md warns about.

    The failure mode was also invisible: the query runs inside a background
    worker whose ``on_error`` only logs, so the exception surfaced as a filter
    panel with EVERY section empty rather than as a traceback. These tests run
    the real thing against a real file-backed DB.
    """

    def test_counts_channels_with_no_tag_of_that_facet(self, session):
        repos = RepositoryFactory(session)
        _tag(repos, _ch(session, "A"), ("genre", "Comedy"))
        _tag(repos, _ch(session, "B"), ("genre", "Drama"), ("subtitle", "English"))
        _ch(session, "C")
        _ch(session, "D")
        session.commit()

        counts = repos.tags.get_facet_untagged_counts()
        assert counts["genre"] == 2, "C and D carry no genre tag"
        assert counts["subtitle"] == 3, "A, C and D carry no subtitle tag"

    def test_a_fully_tagged_facet_reports_nothing(self, session):
        """No row is shown when the facet describes everything — there is no
        gap to explain."""
        repos = RepositoryFactory(session)
        for name in ("A", "B"):
            _tag(repos, _ch(session, name), ("genre", "Comedy"))
        session.commit()

        assert "genre" not in repos.tags.get_facet_untagged_counts()

    def test_counts_and_values_describe_the_same_population(self, session):
        """The footer count and the value counts must sum to the visible total,
        or the row is explaining a gap that isn't there."""
        repos = RepositoryFactory(session)
        _tag(repos, _ch(session, "A"), ("genre", "Comedy"))
        _tag(repos, _ch(session, "B"), ("genre", "Comedy"))
        _tag(repos, _ch(session, "C"), ("genre", "Drama"))
        _ch(session, "D")
        session.commit()

        values = repos.tags.get_facet_value_counts()["genre"]
        untagged = repos.tags.get_facet_untagged_counts()["genre"]
        assert sum(values.values()) + untagged == 4

    def test_hidden_channels_are_excluded_from_the_count(self, session):
        """Same visibility scope as the value counts — a hidden channel must
        not inflate the number the user is shown."""
        from metatv.core.database import ChannelDB

        repos = RepositoryFactory(session)
        _tag(repos, _ch(session, "Visible"), ("genre", "Comedy"))
        hidden_id = _ch(session, "Hidden")
        session.query(ChannelDB).filter_by(id=hidden_id).update({"is_hidden": True})
        _ch(session, "Untagged Visible")
        session.commit()

        assert repos.tags.get_facet_untagged_counts()["genre"] == 1

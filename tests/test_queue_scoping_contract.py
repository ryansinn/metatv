"""``WatchQueueRepository.get_all`` annotates availability; it never drops rows.

Three call sites read this chokepoint and two of them pass
``hidden_provider_ids`` while the third does not:

    sidebar/queue.py:168            get_all(hidden_provider_ids=hidden)
    main_window_favorites.py:318    get_all(hidden_provider_ids=hidden)
    gui/trail_map_data.py:330       get_all()

That reads like drift, and reviewing it is how it was found — but it is correct:
the argument only sets ``available``, and the trail-map seed consumes ids. The
risk was never today's behaviour, it was that nothing stopped someone from
"tidying" the parameter into a filter, which would silently empty the
Unavailable group the queue renders and delete nothing from the DB while
appearing to.

So the invariant is pinned here rather than the call sites being made
artificially identical: the queue is a RECORD view (DR-0007), and disabling a
source must never look like the app dropped what you queued.

Executes the real repository against a real file-backed ``Database`` — the
in-memory shortcut hides session/identity behaviour this depends on.
"""

from __future__ import annotations

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB, WatchQueueDB
from metatv.core.repositories import RepositoryFactory


@pytest.fixture()
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'queue_contract.db'}")
    database.create_tables()
    yield database
    database.close()


@pytest.fixture()
def seeded(db):
    """One live source and one disabled source, each with queued titles."""
    with db.session_scope() as session:
        session.add_all([
            ProviderDB(
                id="live-src", name="Live", type="xtream", url="http://e.com",
                username="u", password="p", is_active=True,
            ),
            ProviderDB(
                id="dead-src", name="Disabled", type="xtream", url="http://e.com",
                username="u", password="p", is_active=False,
            ),
        ])
        for i, pid in enumerate(["live-src", "live-src", "dead-src", "dead-src"]):
            session.add(ChannelDB(
                id=f"ch-{i}", name=f"Title {i}", provider_id=pid,
                media_type="movie", source_id=f"src-{i}",
            ))
            session.add(WatchQueueDB(
                channel_id=f"ch-{i}", channel_name=f"Title {i}",
                media_type="movie", source_id=f"src-{i}", position=i,
            ))
        # An orphan: queued, but its channel no longer exists at all.
        session.add(WatchQueueDB(
            channel_id="ch-gone", channel_name="Deleted Title",
            media_type="movie", source_id="src-gone", position=4,
        ))
    return db


def _both_ways(db):
    """(annotated, unannotated) reads of the same queue in one session."""
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        hidden = set(repos.providers.get_hidden_provider_ids())
        assert hidden, "fixture no longer produces a hidden provider"
        return (
            [(e.channel_id, e.available) for e in
             repos.queue.get_all(hidden_provider_ids=hidden)],
            [(e.channel_id, e.available) for e in repos.queue.get_all()],
        )


def test_the_argument_never_changes_which_rows_come_back(seeded):
    """The invariant the three call sites rely on to be equivalent."""
    annotated, plain = _both_ways(seeded)

    assert [cid for cid, _ in annotated] == [cid for cid, _ in plain], (
        "hidden_provider_ids changed the ROW SET — it is filtering, and the "
        "Watch Queue just silently lost entries on a disabled source"
    )
    assert len(annotated) == 5


def test_it_changes_exactly_one_thing_the_available_flag(seeded):
    """What it does do — and only to the rows on the disabled source."""
    annotated, plain = _both_ways(seeded)

    assert dict(annotated) == {
        "ch-0": True, "ch-1": True,       # live source
        "ch-2": False, "ch-3": False,     # disabled source
        "ch-gone": False,                 # orphan — unavailable either way
    }
    # Without the set, only the orphan is unavailable: nothing else can be known.
    assert dict(plain) == {
        "ch-0": True, "ch-1": True, "ch-2": True, "ch-3": True, "ch-gone": False,
    }


def test_the_trail_map_seed_matches_the_sidebars_id_set(seeded):
    """The actual call sites, run against the same data.

    If they ever diverge, Explore's queue column and the sidebar are showing
    different queues — which is the failure the differing signatures suggested.
    """
    from metatv.gui.trail_map_data import load_queue_ids

    with seeded.session_scope() as session:
        repos = RepositoryFactory(session)
        hidden = set(repos.providers.get_hidden_provider_ids())
        sidebar_ids = [
            e.channel_id for e in repos.queue.get_all(hidden_provider_ids=hidden)
            if e.channel_id
        ]
        seed_ids = load_queue_ids(session)

    assert seed_ids == sidebar_ids


def test_a_disabled_source_does_not_delete_the_queue(seeded):
    """The record-view guarantee, stated as the user experiences it.

    Disabling a source marks those entries recoverable; it must not make them
    vanish. Only the explicit ``clear_unavailable`` action removes them.
    """
    annotated, _ = _both_ways(seeded)
    assert [cid for cid, ok in annotated if not ok] == ["ch-2", "ch-3", "ch-gone"]

    with seeded.session_scope() as session:
        repos = RepositoryFactory(session)
        hidden = set(repos.providers.get_hidden_provider_ids())
        removed = repos.queue.clear_unavailable(hidden)

    assert removed == 3
    with seeded.session_scope() as session:
        remaining = [e.channel_id for e in RepositoryFactory(session).queue.get_all()]
    assert remaining == ["ch-0", "ch-1"], (
        "clear_unavailable is the ONE path that deletes; it must take exactly "
        "the rows get_all annotates unavailable"
    )

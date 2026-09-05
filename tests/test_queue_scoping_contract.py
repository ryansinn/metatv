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


def test_orphan_relocation_never_crosses_providers(db):
    """A recycled provider-native ``source_id`` must not bind an orphaned queue
    row to a DIFFERENT source's channel just because it reused the same small
    native id.

    Provider A's channel ``A_7`` (source_id="7") is gone — simulating a
    refresh that re-keyed it — while an UNRELATED provider B has its own
    channel ``B_7`` also carrying ``source_id="7"``. The orphaned queue row
    must stay orphaned rather than silently attaching to provider B's title.
    Once a genuine successor for provider A shows up (new id, same provider,
    same native source_id), relocation finds THAT one.
    """
    with db.session_scope() as session:
        session.add_all([
            ProviderDB(
                id="A", name="Provider A", type="xtream", url="http://e.com",
                username="u", password="p", is_active=True,
            ),
            ProviderDB(
                id="B", name="Provider B", type="xtream", url="http://e.com",
                username="u", password="p", is_active=True,
            ),
        ])
        # Provider B's own channel that happens to reuse native id "7" — must
        # never be mistaken for provider A's orphaned row.
        session.add(ChannelDB(
            id="B_7", name="Someone Else's Title", provider_id="B",
            media_type="movie", source_id="7",
        ))
        # Queued while it was "A_7" — that channel id no longer exists.
        session.add(WatchQueueDB(
            channel_id="A_7", channel_name="My Queued Title",
            media_type="movie", source_id="7", position=0,
        ))

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        entries = repos.queue.get_all()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.channel is None, (
            "relocation bound the orphaned row to a DIFFERENT provider's "
            "channel just because it reused the same native source_id"
        )
        assert entry.available is False
        assert entry.channel_name == "My Queued Title"

    # A genuine successor for provider A shows up: new synthetic id, same
    # provider, same native source_id. Relocation must find THIS one.
    with db.session_scope() as session:
        session.add(ChannelDB(
            id="A_7v2", name="My Queued Title", provider_id="A",
            media_type="movie", source_id="7",
        ))

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        entries = repos.queue.get_all()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.channel is not None
        assert entry.channel.id == "A_7v2"
        assert entry.provider_id == "A"
        assert entry.available is True


def test_drifted_title_keeps_the_queued_name_not_the_live_one(db):
    """A recycled stream id can leave ``row.channel_id`` pointing at a live
    channel whose title has changed underneath the user (reconnect-mangle).
    ``search_title`` (read by both the sidebar display and its recovery
    search) must carry the STORED queued name when the live name has drifted,
    and the live ``detected_title`` only when the names still agree.
    """
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="P", name="Provider", type="xtream", url="http://e.com",
            username="u", password="p", is_active=True,
        ))
        # Drifted: the channel this row points at now has a DIFFERENT raw name.
        session.add(ChannelDB(
            id="drifted", name="New Title", detected_title="New Title",
            provider_id="P", media_type="movie", source_id="1",
        ))
        session.add(WatchQueueDB(
            channel_id="drifted", channel_name="Old Title",
            media_type="movie", source_id="1", position=0,
        ))
        # Undrifted: raw name still matches what was queued.
        session.add(ChannelDB(
            id="steady", name="Same Title", detected_title="Detected Version",
            provider_id="P", media_type="movie", source_id="2",
        ))
        session.add(WatchQueueDB(
            channel_id="steady", channel_name="Same Title",
            media_type="movie", source_id="2", position=1,
        ))

    with db.session_scope() as session:
        entries = {
            e.channel_id: e for e in RepositoryFactory(session).queue.get_all()
        }

    assert entries["drifted"].search_title == "Old Title", (
        "the sidebar and its recovery search must show the title the user "
        "actually queued, not the recycled stream's new live title"
    )
    assert entries["steady"].search_title == "Detected Version", (
        "when the live name still matches, search_title should read the "
        "live detected_title as before"
    )


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

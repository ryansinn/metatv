"""A watch alert must not fire for a channel on a source you switched off.

``get_programs_starting_soon`` — the desktop-notification path — scoped only
the FEED provider. ``has_future_programmes``, nineteen lines below it, also
scoped the matched CHANNEL's provider, and its docstring already described
itself as this function's sibling "with the same matched-channel and scoping
rules". The symmetry it claimed did not exist.

Those two axes are genuinely different. ``epg_matching.build_match_map`` keeps a
separate ``cross_provider`` candidate dict on purpose, so a programme from an
ACTIVE feed can legitimately be matched to a channel on a DISABLED source. On
the owner's library that was 418 such rows across 6 channels, 18 still in the
future — each one able to raise a toast for something unplayable, which is
`epg_manager`'s own comment about "the absolute gate failing in the most
visible way available to it", via the axis that comment was not about.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.repositories.epg import EpgRepository


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'epg.db'}")
    d.create_tables()
    with d.session_scope() as s:
        s.add(ProviderDB(id="feed-active", name="Active feed", type="xtream", url="http://e.com",
                    username="u", password="p", is_active=True))
        s.add(ProviderDB(id="chan-hidden", name="Disabled source", type="xtream", url="http://e.com",
                    username="u", password="p", is_active=False))
        s.add(ProviderDB(id="chan-active", name="Active source", type="xtream", url="http://e.com",
                    username="u", password="p", is_active=True))
        s.flush()
        # Same feed, two matched channels — one on a hidden source, one not.
        s.add(ChannelDB(id="ch-hidden", source_id=str(uuid.uuid4()),
                        provider_id="chan-hidden", name="Hidden Src Channel",
                        media_type="live"))
        s.add(ChannelDB(id="ch-visible", source_id=str(uuid.uuid4()),
                        provider_id="chan-active", name="Visible Src Channel",
                        media_type="live"))
        s.flush()
        soon = _now() + timedelta(minutes=5)
        s.add(EpgProgramDB(provider_id="feed-active", channel_db_id="ch-hidden",
                           channel_epg_id="x1", channel_name="Hidden Src Channel", title="Match On Hidden Source",
                           start_time=soon, stop_time=soon + timedelta(hours=1)))
        s.add(EpgProgramDB(provider_id="feed-active", channel_db_id="ch-visible",
                           channel_epg_id="x2", channel_name="Visible Src Channel", title="Match On Visible Source",
                           start_time=soon, stop_time=soon + timedelta(hours=1)))
    yield d
    d.close()


def _titles(db, excluded=None):
    with db.session_scope(commit=False) as s:
        rows = EpgRepository(s).get_programs_starting_soon(
            60, ["feed-active"], excluded_channel_provider_ids=excluded)
        return {r.title for r in rows}


def test_without_the_gate_the_hidden_source_programme_leaks(db):
    """The pre-fix behaviour, kept as the contrast that gives the next test meaning.

    Passing nothing must still return both — the parameter is scoping, not an
    unconditional filter, and a caller that has no hidden providers must not
    silently lose rows.
    """
    assert _titles(db) == {"Match On Hidden Source", "Match On Visible Source"}


def test_the_channel_side_gate_drops_it(db):
    assert _titles(db, excluded={"chan-hidden"}) == {"Match On Visible Source"}, (
        "a programme matched to a channel on a hidden source can still raise "
        "a desktop toast")


def test_the_two_axes_are_independent(db):
    """Scoping the FEED cannot catch this — which is why one axis was not enough.

    The programme's own provider_id is the active feed, so every feed-side
    filter in the app passes it through. Only the channel it was matched to
    reveals that it is unplayable.
    """
    with db.session_scope(commit=False) as s:
        rows = EpgRepository(s).get_programs_starting_soon(
            60, ["feed-active"], excluded_channel_provider_ids={"chan-hidden"})
        assert all(r.provider_id == "feed-active" for r in rows), (
            "the surviving row is on the same FEED as the dropped one")


def test_the_notification_path_threads_it(db):
    """The gate is worthless if the one caller does not pass it.

    Source-level, because driving the full 60-second watchlist poll needs a
    live EpgManager, its notification manager and a thread pool — and the thing
    that actually broke was a missing keyword argument.
    """
    import inspect

    from metatv.core.epg_manager import EpgManager

    src = inspect.getsource(EpgManager._check_watchlist_notifications)
    assert "get_programs_starting_soon(" in src
    assert "excluded_channel_provider_ids=" in src, (
        "_check_watchlist_notifications resolves the hidden set and must pass "
        "it on BOTH axes, not just to the feed list")

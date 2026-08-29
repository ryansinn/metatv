"""The dead-stream comparison query must not run when no channel is dead.

Answering "how many rows does the dead-stream gate hide" means re-running the
whole channel query with that gate lifted and diffing the two result sets. That
comparison inherits everything the main query does — including the variant
collapse, whose window function runs over the full corpus regardless of LIMIT.
Measured on the owner's library: **6.5 s**, on top of the main query's own 6 s.

``docs/ENGINEERING_DECISIONS.md`` §6 sized this pair at "414 ms against a load
of 1.1 ms". That was true when written; the collapse path shipped afterwards and
the comparison was never re-measured against it.

The gate cannot hide what does not exist. With no row in ``reliability_state =
'dead'`` the count is **exactly 0** — not a floor, not an estimate — so the
comparison is a provable no-op. ``stream_retry`` is empty on the owner's live
database and on any install where no stream has failed six times.

These tests assert the DECISION, by counting the queries the load path issues:
a comparison that runs and returns 0 is indistinguishable from one that was
skipped if you only look at the count it produced.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB, StreamRetryDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui.main_window_channels import _ChannelListMixin


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def session(tmp_path: Path):
    db = Database(f"sqlite:///{tmp_path / 'dead_probe.db'}")
    db.create_tables()
    s = db.get_session()
    s.add(ProviderDB(id="p1", name="Test Source", type="xtream",
                     url="http://example", is_active=True, account_status="Active"))
    s.commit()
    yield s
    s.close()
    db.close()


def _ch(session, name: str) -> str:
    ch = ChannelDB(id=str(uuid.uuid4()), source_id=str(uuid.uuid4()),
                   provider_id="p1", name=name, media_type="movie",
                   is_hidden=False, detected_title=name)
    session.add(ch)
    session.flush()
    return ch.id


def _mark_dead(session, channel_id: str) -> None:
    session.add(StreamRetryDB(id=str(uuid.uuid4()), channel_id=channel_id,
                              channel_name="dead", reliability_state="dead",
                              play_fail_count=6))


def _params(**overrides) -> dict:
    base = {
        "provider_id": None, "media_types": ["live", "movie", "series"],
        "language_prefixes": None, "region_prefixes": None,
        "quality_prefixes": None, "platform_prefixes": None,
        "genre_filters": None, "invert_prefix_filters": False,
        "include_untagged": True, "include_untagged_quality": True,
        "adult_mode": "all", "force_adult_ids": [], "tag_includes": None,
        "source_categories": None, "excluded_prefixes": set(),
        "excluded_user_categories": set(), "bypass_global_exclusions": False,
        "bypass_dead_gate": False, "search_query": None,
        "strict_genre_filter": None, "person_filter": None,
        "context_tag_filter": None, "context_category_filter": None,
        "context_id_filter": None, "id_filter_show_all": False,
        "page_size": 1000, "show_provider_icon": False,
        "provider_icon_map": {}, "given_provider_id": None,
        "hidden_only": False, "bypassing_tier1": False, "hide_watched": False,
    }
    base.update(overrides)
    return base


class _CountingRepos:
    """RepositoryFactory wrapper that records every ``channels.get_all`` call."""

    def __init__(self, session):
        self._inner = RepositoryFactory(session)
        self.get_all_calls: list[dict] = []
        outer = self

        class _Channels:
            def __getattr__(self, name):
                return getattr(outer._inner.channels, name)

            def get_all(self, **kwargs):
                outer.get_all_calls.append(kwargs)
                return outer._inner.channels.get_all(**kwargs)

        self.channels = _Channels()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def dead_comparisons(self) -> int:
        return sum(1 for k in self.get_all_calls if k.get("include_dead"))


def test_no_dead_row_means_no_comparison_query(session):
    """THE assertion. Pre-fix the 6.5 s comparison runs anyway and returns 0."""
    _ch(session, "Normal Channel")
    _ch(session, "Another Channel")
    session.commit()

    repos = _CountingRepos(session)
    _dtos, out = _ChannelListMixin._query_channels(repos, _params())

    assert repos.dead_comparisons == 0, (
        "the dead-stream comparison ran with an empty stream_retry table — it "
        "can only return 0, and it costs a full second query"
    )
    assert out["hidden_by_dead"] == 0, "nothing is hidden, so the count is 0"


def test_a_dead_row_still_gets_counted(session):
    """The skip must not cost the feature: one dead row and it measures again."""
    normal_id = _ch(session, "Normal Channel")
    dead_id = _ch(session, "Flaky Channel")
    _mark_dead(session, dead_id)
    session.commit()

    repos = _CountingRepos(session)
    dtos, out = _ChannelListMixin._query_channels(repos, _params())

    assert repos.dead_comparisons == 1, "the comparison must run when a row is dead"
    assert [d.id for d in dtos] == [normal_id]
    assert out["hidden_by_dead"] == 1, "the dead row is still counted"


def test_the_count_is_exact_not_a_floor_when_nothing_is_dead(session):
    """Skipping must not silently downgrade the count to an estimate.

    The transparency row renders "N hidden" differently from "at least N
    hidden"; a skip that left the floor flag set would change what the user
    reads, which is precisely the mirror-not-cage promise this layer exists for.
    """
    for i in range(5):
        _ch(session, f"Channel {i}")
    session.commit()

    repos = _CountingRepos(session)
    _dtos, out = _ChannelListMixin._query_channels(repos, _params())

    assert out["hidden_by_dead"] == 0
    assert not out.get("hidden_by_dead_is_floor"), (
        "with nothing dead the count is exactly 0, never a floor"
    )


def test_the_probe_itself_does_not_scan(session):
    """``has_dead`` is an existence probe, not a map build.

    ``get_reliability_map`` loads every non-ok row; using it here would trade a
    6.5 s query for a full-table read on the very install where the table is
    large (many failing streams), which is the opposite of the intent.
    """
    for i in range(50):
        cid = _ch(session, f"Flaky {i}")
        _mark_dead(session, cid)
    session.commit()

    repos = RepositoryFactory(session)
    assert repos.stream_retry.has_dead() is True

    session.query(StreamRetryDB).delete()
    session.commit()
    assert repos.stream_retry.has_dead() is False

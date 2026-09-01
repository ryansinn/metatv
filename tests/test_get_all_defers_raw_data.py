"""`get_all()` must not select the raw_data blob.

It is the busiest query in the app — every list render, every search, every
filter change — and `raw_data` is ~369 MB across 785,489 rows, roughly a third
of the channels table. Nothing on this path reads it: `ChannelListDTO` does not
carry the field and no caller of `get_all()` touches it.

Measured on the owner's real database, a 2000-row page:

    with raw_data   923 ms
    deferred         52 ms      17.8x

The assertion is on the EMITTED SQL, not on timing. A timing test would be
flaky on CI and would not say *why* it got slower; the column list says exactly
what changed. And `defer()` is transparent — a caller that did read
`.raw_data` still gets it via a lazy load — so the failure mode of losing this
is a silent N+1, never an error. Nothing else would notice.
"""

from __future__ import annotations

import pytest

from metatv.core.database import Database


@pytest.fixture
def repos(tmp_path):
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'defer.db'}")
    db.create_tables()
    with db.session_scope() as session:
        yield RepositoryFactory(session)


def _compiled(query) -> str:
    return str(query.statement.compile(compile_kwargs={"literal_binds": False}))


def test_get_all_does_not_select_raw_data(repos, monkeypatch):
    """The column must be absent from the SELECT list."""
    from metatv.core.repositories import channel as channel_mod

    captured = {}
    original = channel_mod.ChannelRepository._apply_channel_filters

    def spy(self, query, *a, **kw):
        captured["query"] = query
        return original(self, query, *a, **kw)

    monkeypatch.setattr(channel_mod.ChannelRepository,
                        "_apply_channel_filters", spy)
    repos.channels.get_all(limit=1)

    sql = _compiled(captured["query"])
    assert "channels.raw_data" not in sql, (
        "get_all is selecting raw_data again — ~369 MB of JSON on the app's "
        "busiest query, for a column nothing on this path reads")


def test_a_column_that_is_read_is_still_selected(repos, monkeypatch):
    """Non-degeneracy: prove the check can tell the difference.

    Without this, the assertion above would also pass against a query that
    selected nothing at all, or against a compile that silently returned "".
    """
    from metatv.core.repositories import channel as channel_mod

    captured = {}
    original = channel_mod.ChannelRepository._apply_channel_filters

    def spy(self, query, *a, **kw):
        captured["query"] = query
        return original(self, query, *a, **kw)

    monkeypatch.setattr(channel_mod.ChannelRepository,
                        "_apply_channel_filters", spy)
    repos.channels.get_all(limit=1)

    sql = _compiled(captured["query"])
    for column in ("channels.id", "channels.name", "channels.detected_title"):
        assert column in sql, f"{column} is read by the list and must be selected"


def test_reading_raw_data_still_works_if_someone_needs_it(repos):
    """defer() is transparent, and that is why losing this fails silently.

    A future caller that reads .raw_data gets it lazily rather than an error —
    correct, but a per-row query. Recorded here so the cost is understood
    rather than discovered.
    """
    from metatv.core.database import ChannelDB

    repos.session.add(ChannelDB(
        id="p1_1", source_id="1", provider_id="p1", name="A Movie",
        stream_url="http://x/m.mkv", media_type="movie",
        raw_data={"rating": "7.5"}))
    repos.session.flush()

    rows = repos.channels.get_all(limit=10)
    assert rows, "fixture produced no rows"

    row = repos.session.get(ChannelDB, "p1_1")
    assert row.raw_data == {"rating": "7.5"}, "the column is unreadable, not deferred"

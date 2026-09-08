"""Behavioral tests for DB-2 — the play path derives ``stream_url`` at play
time instead of trusting the stored, credentialed ``ChannelDB.stream_url``.

``core/stream_url_derivation.derive_channel_stream_url`` is the chokepoint
``main_window_streaming.play_media`` calls; this proves it builds the correct
playable URL from the provider + channel alone, with no stored ``stream_url``
in the picture at all — the shape that lets the column eventually be dropped
once every reader converts (CLAUDE.md: keep the column as a transitional read
until then).

All DB tests use a file-backed (tmp_path) SQLite ``Database`` — never
``:memory:`` — per CLAUDE.md's tests rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest


@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'db2_derivation.db'}")
    d.create_tables()
    yield d
    d.close()


def _add_xtream_provider(db, *, provider_id="p1", url="http://host.example.com",
                          username="user1", password="pass1") -> None:
    from metatv.core.database import ProviderDB

    with db.session_scope() as session:
        session.add(ProviderDB(
            id=provider_id, name="Test Provider", type="xtream",
            url=url, username=username, password=password, is_active=True,
        ))


@dataclass
class _FakeChannel:
    """Deliberately carries NO ``stream_url`` attribute — the derivation must
    not need one; only ``provider_id``/``source_id``/``media_type``/``raw_data``."""
    provider_id: str
    source_id: str
    media_type: str
    raw_data: Optional[dict] = None


class TestDeriveChannelStreamUrl:
    def test_builds_the_correct_url_from_provider_and_channel_alone(self, db):
        from metatv.core.stream_url_derivation import derive_channel_stream_url

        _add_xtream_provider(db)
        channel = _FakeChannel(
            provider_id="p1", source_id="12345", media_type="movie",
            raw_data={"container_extension": "mkv"},
        )
        url = derive_channel_stream_url(db, channel)
        assert url == "http://host.example.com/movie/user1/pass1/12345.mkv", (
            f"Got {url!r}"
        )

    def test_defaults_extension_to_ts_when_raw_data_carries_none(self, db):
        from metatv.core.stream_url_derivation import derive_channel_stream_url

        _add_xtream_provider(db)
        channel = _FakeChannel(provider_id="p1", source_id="999", media_type="live", raw_data=None)
        url = derive_channel_stream_url(db, channel)
        assert url == "http://host.example.com/live/user1/pass1/999.ts"

    def test_series_media_type_builds_the_series_path(self, db):
        from metatv.core.stream_url_derivation import derive_channel_stream_url

        _add_xtream_provider(db)
        channel = _FakeChannel(provider_id="p1", source_id="45619", media_type="series")
        url = derive_channel_stream_url(db, channel)
        assert url == "http://host.example.com/series/user1/pass1/45619.ts"

    def test_unknown_provider_id_returns_none(self, db):
        """Falls back to the caller reading the transitional stored column."""
        from metatv.core.stream_url_derivation import derive_channel_stream_url

        channel = _FakeChannel(provider_id="does-not-exist", source_id="1", media_type="movie")
        assert derive_channel_stream_url(db, channel) is None

    def test_non_xtream_provider_type_returns_none(self, db):
        """No other provider plugin exists yet — the derivation must not guess
        a URL shape for a type it does not know how to build."""
        from metatv.core.stream_url_derivation import derive_channel_stream_url

        _add_xtream_provider(db, provider_id="p2")
        with db.session_scope() as session:
            from metatv.core.database import ProviderDB
            row = session.query(ProviderDB).filter_by(id="p2").one()
            row.type = "m3u"
        channel = _FakeChannel(provider_id="p2", source_id="1", media_type="movie")
        assert derive_channel_stream_url(db, channel) is None


class TestPlayMediaUsesDerivationNotStoredColumn:
    def test_play_media_reads_derive_channel_stream_url_before_the_stored_column(self):
        """Static proof the play path calls the chokepoint: play_media's own
        source imports and calls ``derive_channel_stream_url`` — the single
        play path DB-2 converts (CLAUDE.md: keep the column transitional
        elsewhere, convert the one play path first)."""
        import inspect

        from metatv.gui import main_window_streaming

        assert "derive_channel_stream_url" in main_window_streaming.__dict__, (
            "main_window_streaming.py must import derive_channel_stream_url"
        )
        source = inspect.getsource(main_window_streaming._StreamingMixin.play_media)
        assert "derive_channel_stream_url(self.db, channel)" in source, (
            "play_media must derive the URL fresh rather than trust "
            "channel.stream_url unconditionally"
        )

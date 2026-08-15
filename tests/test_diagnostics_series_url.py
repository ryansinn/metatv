"""Test stream diagnostics for series channels (issue #NNN).

Tests that the diagnostics dialog resolves to a representative episode's stream
URL for series channels, rather than testing a synthetic series URL that is
never actually streamed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

from metatv.core.database import Database, ChannelDB, EpisodeDB, SeasonDB
from metatv.core.models import MediaType
from metatv.gui.diagnostics_dialog import StreamDiagnosticsDialog
from metatv.gui.main_window_favorites import _FavoritesMixin


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """Create a temporary in-process database for testing."""
    db_path = tmp_path / "test.db"
    # SQLite URL format: sqlite:///path/to/file
    db_url = f"sqlite:///{db_path}"
    db = Database(db_url)
    db.create_tables()
    return db


class _MinimalHost(_FavoritesMixin):
    """Minimal host for testing _FavoritesMixin methods."""

    def __init__(self, db: Database):
        self.db = db


class TestSeriesDiagnosticUrl:
    """Test suite for series diagnostics URL resolution."""

    def test_series_resolves_to_episode_url(self, tmp_db: Database) -> None:
        """Test 1: A series channel resolves to the episode's stream_url, not the series' stored one.

        This test calls the production _resolve_diagnostic_target() directly and
        MUST FAIL against the pre-fix code (which used channel.stream_url for all
        channel types, never checking episodes).
        """
        # Set up: create a series channel and an episode
        with tmp_db.session_scope() as session:
            # Series channel with a fake series URL (never actually played)
            series_ch = ChannelDB(
                id="ch_series_1",
                source_id="series_123",
                provider_id="provider_1",
                name="Test Series",
                media_type=MediaType.SERIES,
                stream_url="http://server/series/user/pass/123.ts",  # Series URL
            )
            session.add(series_ch)

            # Season record (required by EpisodeDB)
            season = SeasonDB(
                id="season_1_1",
                series_id="series_123",
                provider_id="provider_1",
                season_number=1,
            )
            session.add(season)

            # Episode with real stream URL (what actually plays)
            ep = EpisodeDB(
                id="ep_1",
                series_id="series_123",
                provider_id="provider_1",
                season_id="season_1_1",
                episode_id="1",
                title="Episode 1",
                series_name="Test Series",
                season_num=1,
                episode_num=1,
                stream_url="http://server/series/user/pass/1485215.mp4",  # Episode URL
                container_extension="mp4",
            )
            session.add(ep)
            session.commit()

        # Test: Call the production method directly
        host = _MinimalHost(tmp_db)
        with tmp_db.session_scope() as session:
            stream_url, name, episode_label = host._resolve_diagnostic_target(session, "ch_series_1")

        # Assert: the URL should be the episode's URL, not the series' stored URL
        assert stream_url == "http://server/series/user/pass/1485215.mp4", \
            f"Expected episode URL, got {stream_url}"
        assert name == "Test Series", f"Expected 'Test Series', got {name}"
        assert episode_label == "S01E01", f"Expected S01E01, got {episode_label}"

    def test_series_prefers_last_played_episode(self, tmp_db: Database) -> None:
        """Test 2a: When a watched episode exists, it is chosen over the first episode."""
        with tmp_db.session_scope() as session:
            series_ch = ChannelDB(
                id="ch_series_2",
                source_id="series_200",
                provider_id="provider_1",
                name="Multi-Episode Series",
                media_type=MediaType.SERIES,
                stream_url="http://server/series/user/pass/200.ts",
            )
            session.add(series_ch)

            season = SeasonDB(
                id="season_2_1",
                series_id="series_200",
                provider_id="provider_1",
                season_number=1,
            )
            session.add(season)

            # Add multiple episodes
            ep1 = EpisodeDB(
                id="ep_2_1",
                series_id="series_200",
                provider_id="provider_1",
                season_id="season_2_1",
                episode_id="1",
                title="Episode 1",
                series_name="Multi-Episode Series",
                season_num=1,
                episode_num=1,
                stream_url="http://server/series/user/pass/2001.mp4",
                container_extension="mp4",
            )
            ep3 = EpisodeDB(
                id="ep_2_3",
                series_id="series_200",
                provider_id="provider_1",
                season_id="season_2_1",
                episode_id="3",
                title="Episode 3",
                series_name="Multi-Episode Series",
                season_num=1,
                episode_num=3,
                stream_url="http://server/series/user/pass/2003.mp4",
                container_extension="mp4",
                last_played=datetime(2026, 8, 1, 12, 0, 0),  # Watched most recently
            )
            session.add(ep1)
            session.add(ep3)
            session.commit()

        # Test: Call the production method
        host = _MinimalHost(tmp_db)
        with tmp_db.session_scope() as session:
            stream_url, name, episode_label = host._resolve_diagnostic_target(session, "ch_series_2")

        # Assert: should resolve to the last-played episode
        assert stream_url == "http://server/series/user/pass/2003.mp4", \
            f"Expected last-played episode URL, got {stream_url}"
        assert episode_label == "S01E03", f"Expected S01E03, got {episode_label}"

    def test_series_falls_back_to_first_episode_no_watch_history(self, tmp_db: Database) -> None:
        """Test 2b: When no episode has been watched, the first by season/episode order is chosen."""
        with tmp_db.session_scope() as session:
            series_ch = ChannelDB(
                id="ch_series_3",
                source_id="series_300",
                provider_id="provider_1",
                name="Unplayed Series",
                media_type=MediaType.SERIES,
                stream_url="http://server/series/user/pass/300.ts",
            )
            session.add(series_ch)

            season = SeasonDB(
                id="season_3_1",
                series_id="series_300",
                provider_id="provider_1",
                season_number=1,
            )
            session.add(season)

            # Add episodes with no watch history (intentionally added out of order)
            ep2 = EpisodeDB(
                id="ep_3_2",
                series_id="series_300",
                provider_id="provider_1",
                season_id="season_3_1",
                episode_id="2",
                title="Episode 2",
                series_name="Unplayed Series",
                season_num=1,
                episode_num=2,
                stream_url="http://server/series/user/pass/3002.mp4",
                container_extension="mp4",
            )
            ep1 = EpisodeDB(
                id="ep_3_1",
                series_id="series_300",
                provider_id="provider_1",
                season_id="season_3_1",
                episode_id="1",
                title="Episode 1",
                series_name="Unplayed Series",
                season_num=1,
                episode_num=1,
                stream_url="http://server/series/user/pass/3001.mp4",
                container_extension="mp4",
            )
            session.add(ep2)
            session.add(ep1)
            session.commit()

        # Test: Call the production method
        host = _MinimalHost(tmp_db)
        with tmp_db.session_scope() as session:
            stream_url, name, episode_label = host._resolve_diagnostic_target(session, "ch_series_3")

        # Assert: should resolve to the first episode by season/episode order
        assert stream_url == "http://server/series/user/pass/3001.mp4", \
            f"Expected first episode URL, got {stream_url}"
        assert episode_label == "S01E01", f"Expected S01E01, got {episode_label}"

    def test_series_with_no_episodes_falls_back_to_channel_url(self, tmp_db: Database) -> None:
        """Test 3: A series with zero episodes falls back to the channel URL and does not crash."""
        with tmp_db.session_scope() as session:
            # Series channel with no episodes
            series_ch = ChannelDB(
                id="ch_series_empty",
                source_id="series_empty",
                provider_id="provider_1",
                name="Empty Series",
                media_type=MediaType.SERIES,
                stream_url="http://server/series/user/pass/empty.ts",
            )
            session.add(series_ch)
            session.commit()

        # Test: Call the production method
        host = _MinimalHost(tmp_db)
        with tmp_db.session_scope() as session:
            stream_url, name, episode_label = host._resolve_diagnostic_target(session, "ch_series_empty")

        # Assert: falls back to channel URL
        assert stream_url == "http://server/series/user/pass/empty.ts"
        assert name == "Empty Series"
        assert episode_label == ""  # No episode was found

    def test_movie_channel_unaffected(self, tmp_db: Database) -> None:
        """Test 4: A MOVIE channel is unaffected and still uses its own stream_url."""
        with tmp_db.session_scope() as session:
            movie_ch = ChannelDB(
                id="ch_movie_1",
                source_id="movie_123",
                provider_id="provider_1",
                name="Test Movie",
                media_type=MediaType.MOVIE,
                stream_url="http://server/movie/user/pass/123.mp4",
            )
            session.add(movie_ch)
            session.commit()

        # Test: Call the production method
        host = _MinimalHost(tmp_db)
        with tmp_db.session_scope() as session:
            stream_url, name, episode_label = host._resolve_diagnostic_target(session, "ch_movie_1")

        # Assert: MOVIE channels should not trigger episode resolution
        assert stream_url == "http://server/movie/user/pass/123.mp4"
        assert name == "Test Movie"
        assert episode_label == ""

    def test_dialog_renders_correct_button_text_no_lone_ampersand(self, qapp: QApplication) -> None:
        """Test 5: The 'Apply tuning && Save' button source code uses '&&' for a literal '&'."""
        dialog = StreamDiagnosticsDialog(
            channel_name="Test Channel",
            stream_url="http://server/live/user/pass/123.ts",
            config=type('Config', (), {
                'diagnostics_sample_seconds': 8,
                'diagnostics_baseline_url': None,
            })(),
            executor=type('Executor', (), {'submit': lambda x: None})(),
            player_active=False,
            episode_label="",
        )

        # Find the apply button
        apply_button = dialog._apply_button
        assert isinstance(apply_button, QPushButton)

        # button.text() returns the text that was set. When we pass "Apply tuning && Save",
        # Qt stores it as-is internally. The mnemonic processing (converting && to &)
        # happens at render time. So we check that the source was created with '&&'.
        button_text = apply_button.text()
        assert button_text == "Apply tuning && Save", \
            f"Button should be created with '&&' for a literal ampersand, got '{button_text}'"

    def test_dialog_shows_redacted_url_line(self, qapp: QApplication) -> None:
        """Test 5: The dialog shows a redacted URL line with optional episode code."""
        stream_url = "http://server/series/myuser/mypass/123.ts"
        dialog = StreamDiagnosticsDialog(
            channel_name="Test Series",
            stream_url=stream_url,
            config=type('Config', (), {
                'diagnostics_sample_seconds': 8,
                'diagnostics_baseline_url': None,
            })(),
            executor=type('Executor', (), {'submit': lambda x: None})(),
            player_active=False,
            episode_label="S01E01",
        )

        # Check the URL line exists (it's created during _setup_ui)
        assert hasattr(dialog, '_url_line'), "Dialog should have _url_line attribute"

        # Check the rendered text contains redacted URL (no credentials)
        url_text = dialog._url_line.text()
        assert "***" in url_text, f"URL should contain redacted credentials: {url_text}"
        assert "myuser" not in url_text, f"URL should not contain username: {url_text}"
        assert "mypass" not in url_text, f"URL should not contain password: {url_text}"

        # Check episode label is shown when provided
        assert "S01E01" in url_text, f"Episode label should be in URL line: {url_text}"

        # Verify the URL line is part of the dialog layout (which means it will be shown when the dialog is displayed)
        assert dialog._url_line.parent() is not None, "URL line should be parented to the dialog"

    def test_dialog_episode_label_optional(self, qapp: QApplication) -> None:
        """Test 5: When no episode label is provided, URL line shows only the redacted URL."""
        dialog = StreamDiagnosticsDialog(
            channel_name="Test Movie",
            stream_url="http://server/movie/user/pass/456.mp4",
            config=type('Config', (), {
                'diagnostics_sample_seconds': 8,
                'diagnostics_baseline_url': None,
            })(),
            executor=type('Executor', (), {'submit': lambda x: None})(),
            player_active=False,
            episode_label="",  # No episode label
        )

        url_text = dialog._url_line.text()
        # Should start with "Testing" and contain redacted URL
        assert url_text.startswith("Testing"), f"URL line should start with 'Testing': {url_text}"
        assert "***" in url_text, f"URL should be redacted: {url_text}"

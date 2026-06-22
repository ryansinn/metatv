"""Behavioral test: Migration Center log messages interpolate values correctly.

Loguru uses brace-style ``{}`` interpolation (lazy str.format), NOT printf ``%d``/``%s``.
This test verifies that an interpolating log line in TagBackfillTask actually embeds
the value rather than printing the literal placeholder.

The test drives ``TagBackfillTask.run()`` against a tiny file-backed DB (per CLAUDE.md:
not ``:memory:``), captures rendered log messages via a loguru sink, and asserts the
captured line contains the channel count as a digit and does NOT contain ``%d`` or ``{}``.

This catches the regression where printf-style ``%d``/``%s`` placeholders silently drop
args under loguru (the args are passed but loguru formats with str.format, leaving the
literal ``%d`` in the output).
"""

from __future__ import annotations

import uuid

import pytest
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import ChannelDB, Database
from metatv.core.migrations.tag_backfill import TagBackfillTask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created."""
    db_path = tmp_path / "test_loguru.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def cfg(tmp_path):
    """Isolated Config instance; config_dir points to tmp_path, not ~/.config/metatv."""
    return Config(config_dir=tmp_path / "cfg")


def _seed_channels(db: Database, count: int) -> None:
    """Insert *count* minimal ChannelDB rows."""
    with db.session_scope() as session:
        for i in range(count):
            session.add(
                ChannelDB(
                    id=str(uuid.uuid4()),
                    source_id=str(uuid.uuid4()),
                    provider_id="test_provider",
                    name=f"Test Channel {i}",
                )
            )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_tag_backfill_log_interpolates_channel_count(file_db, cfg):
    """The 'processing N channels' log line contains the actual count, not a placeholder.

    Regression: when placeholders were printf-style (``%d``), loguru's str.format pass
    left ``%d`` in the rendered string and silently ignored the args.  This test seeds 3
    channels, runs the backfill, captures every loguru message emitted by TagBackfillTask,
    and asserts:
    - At least one message contains "3" (the channel count as a digit).
    - No message contains the literal string ``%d`` or unformatted ``{}``.
    """
    _seed_channels(file_db, 3)

    captured: list[str] = []

    # Add a loguru sink that appends the fully rendered message text.
    sink_id = logger.add(lambda msg: captured.append(msg.record["message"]), level="DEBUG")
    try:
        task = TagBackfillTask(file_db, config=cfg)
        task.run(progress_cb=lambda done, total: None, is_cancelled=lambda: False)
    finally:
        logger.remove(sink_id)

    # Filter to lines from TagBackfillTask (all start with "TagBackfillTask:")
    backfill_msgs = [m for m in captured if m.startswith("TagBackfillTask:")]

    assert backfill_msgs, "TagBackfillTask emitted no log messages at all"

    # The "processing N channels" line must exist and contain "3", not a placeholder.
    processing_lines = [m for m in backfill_msgs if "processing" in m and "channel" in m]
    assert processing_lines, (
        f"No 'processing ... channels' line found in: {backfill_msgs}"
    )
    processing_msg = processing_lines[0]

    # Must contain the actual count (3) as a digit.
    assert "3" in processing_msg, (
        f"Expected channel count '3' in log message, got: {processing_msg!r}"
    )

    # Must not contain the unformatted placeholder forms.
    assert "%d" not in processing_msg, (
        f"Found literal '%d' placeholder in log message (printf leak): {processing_msg!r}"
    )
    assert "{}" not in processing_msg, (
        f"Found unformatted '{{}}' placeholder in log message: {processing_msg!r}"
    )

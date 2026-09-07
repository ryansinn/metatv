"""Tests for PPV/event placeholder row exclusion.

Placeholder rows are injected by providers to fill PPV slot bundles when no event
is scheduled (e.g. ``- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 ...``).
They are NOT playable streams and must be excluded from every content surface.

Coverage:
- ``ChannelRepository.get_all()`` — placeholder rows seeded in DB are excluded; normal
  channels alongside them still appear, via the SQL ``NOT LIKE '%NO EVENT STREAMING%'``
  clause in ``get_all()`` (``core/repositories/channel.py``).

(The Python-side ``is_event_placeholder()`` helper this file used to also cover was
Sports/Events view residue — the view that would have called it was retired in #731,
and ``get_all()`` never called it — so it was deleted in dead-code sweep B along with
its dedicated unit tests. See docs/REFACTOR_PLAN.md row D43.)
"""
import pytest

from tests.conftest import make_channel


# ── get_all SQL exclusion tests ───────────────────────────────────────────────

@pytest.fixture
def channels_with_placeholder(db_session):
    """Seed one normal channel and one placeholder row."""
    normal = make_channel(db_session, "DE: DYN PPV 13 HD", detected_prefix="DE")
    placeholder = make_channel(
        db_session,
        "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 [DE| DYN PPV EXCLUSIVE]",
    )
    db_session.commit()
    return {"normal": normal, "placeholder": placeholder}


def test_get_all_excludes_placeholder(repo, channels_with_placeholder) -> None:
    """get_all() must exclude NO EVENT STREAMING placeholder rows."""
    result = repo.get_all()
    names = {c.name for c in result}
    assert "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 [DE| DYN PPV EXCLUSIVE]" not in names


def test_get_all_keeps_real_channel_alongside_placeholder(repo, channels_with_placeholder) -> None:
    """get_all() keeps real channels that live alongside placeholder rows."""
    result = repo.get_all()
    names = {c.name for c in result}
    assert "DE: DYN PPV 13 HD" in names


def test_get_all_excludes_multiple_placeholder_variants(db_session, repo) -> None:
    """All placeholder variants from the bug report are excluded."""
    make_channel(
        db_session,
        "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 [DE| DYN PPV EXCLUSIVE]",
    )
    make_channel(
        db_session,
        "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: SPORT DEUTSCHLAND PPV 1",
    )
    make_channel(
        db_session,
        "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DISNEY+ PPV 21",
    )
    make_channel(db_session, "DE: DISNEY+ HD", detected_prefix="DE")
    db_session.commit()

    result = repo.get_all()
    names = {c.name for c in result}

    assert "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 [DE| DYN PPV EXCLUSIVE]" not in names
    assert "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: SPORT DEUTSCHLAND PPV 1" not in names
    assert "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DISNEY+ PPV 21" not in names
    assert "DE: DISNEY+ HD" in names


def test_get_all_real_ppv_slot_is_not_excluded(db_session, repo) -> None:
    """A real PPV channel (no 'NO EVENT STREAMING') must NOT be excluded."""
    make_channel(db_session, "DE: DYN PPV 13 [DE| DYN PPV EXCLUSIVE]", detected_prefix="DE")
    db_session.commit()

    result = repo.get_all()
    names = {c.name for c in result}
    assert "DE: DYN PPV 13 [DE| DYN PPV EXCLUSIVE]" in names

"""Tests for PPV/event placeholder row detection and exclusion.

Placeholder rows are injected by providers to fill PPV slot bundles when no event
is scheduled (e.g. ``- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 ...``).
They are NOT playable streams and must be excluded from every content surface.

Coverage:
- ``is_event_placeholder()`` — True for placeholder patterns, False for real channels.
- ``ChannelRepository.get_all()`` — placeholder rows seeded in DB are excluded; normal
  channels alongside them still appear.
"""
import pytest

from metatv.core.channel_name_utils import is_event_placeholder
from tests.conftest import make_channel


# ── is_event_placeholder unit tests ──────────────────────────────────────────

@pytest.mark.parametrize("name", [
    # Exact real-world examples from the bug report
    "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 [DE| DYN PPV EXCLUSIVE]",
    "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: SPORT DEUTSCHLAND PPV 1",
    "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DISNEY+ PPV 21",
    # Minimal marker — just the substring
    "NO EVENT STREAMING",
    # Case variants the .upper() guard must handle
    "- no event streaming - | foo",
    "- No Event Streaming - | bar",
    # ARG provider variant
    "- NO EVENT STREAMING - | 8K EXCLUSIVE | ARG: FANATIZ PPV 10",
])
def test_is_event_placeholder_true(name: str) -> None:
    """Names containing 'NO EVENT STREAMING' (any case) are placeholders."""
    assert is_event_placeholder(name) is True


@pytest.mark.parametrize("name", [
    # Real channels that contain the word EVENT but are not placeholders
    "EN | UEFA Champions League EVENT",
    "SPORT EVENT CHANNEL HD",
    "- DE: DYN PPV 13 -",          # real PPV slot with no placeholder marker
    "D+ Disney+",
    "BEIN SPORTS HD",
    "",                             # empty string
    "STREAMING LIVE NOW",           # contains STREAMING but not the full marker
    "NO EVENT TODAY",               # contains NO and EVENT but not the full marker
])
def test_is_event_placeholder_false(name: str) -> None:
    """Real channels and non-placeholder names are not flagged."""
    assert is_event_placeholder(name) is False


def test_is_event_placeholder_empty_string() -> None:
    """Empty string returns False without raising."""
    assert is_event_placeholder("") is False


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

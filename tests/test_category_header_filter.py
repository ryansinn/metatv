"""Tests for provider category-header row detection and exclusion.

Category headers are label rows injected by some providers to group channels in
the source playlist (e.g. ``##### BEIN SPORTS #####``). They are not playable
streams and must be excluded from every content surface.

Coverage:
- ``is_category_header()`` — True for header patterns, False for real channels.
- ``ChannelRepository.get_all()`` — header rows seeded in DB are excluded; normal
  channels alongside them still appear.
"""
import pytest

from metatv.core.channel_name_utils import is_category_header
from tests.conftest import make_channel


# ── is_category_header unit tests ────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "##### BEIN SPORTS #####",
    "###### RELAX 4K ######",
    "##### BE SPORTS HD ##### · HD",
    "##CATEGORY",           # minimal 2-hash form
    "###",                  # all hashes, still a header
])
def test_is_category_header_true(name: str) -> None:
    """Names starting with ≥2 '#' are category headers."""
    assert is_category_header(name) is True


@pytest.mark.parametrize("name", [
    "BEIN SPORTS",          # no hash at all
    "CH#5",                 # interior hash, not leading
    "D+ Disney",            # normal channel
    "#1 News",              # single leading hash — NOT a header
    "",                     # empty string
    "   #1 News",           # leading whitespace + single hash — not a header
])
def test_is_category_header_false(name: str) -> None:
    """Normal channel names (single '#', interior '#', or no '#') are not headers."""
    assert is_category_header(name) is False


def test_is_category_header_leading_whitespace_with_two_hashes() -> None:
    """Leading whitespace before '##' still counts as a header."""
    assert is_category_header("  ## SECTION ##") is True


# ── get_all SQL exclusion tests ──────────────────────────────────────────────

@pytest.fixture
def channels_with_header(db_session):
    """Seed one normal channel and one category-header row."""
    normal = make_channel(db_session, "BEIN SPORTS HD", detected_prefix="BEIN")
    header = make_channel(db_session, "##### BEIN SPORTS #####")
    db_session.commit()
    return {"normal": normal, "header": header}


def test_get_all_excludes_category_header(repo, channels_with_header) -> None:
    """get_all() must exclude category-header rows from results."""
    result = repo.get_all()
    names = {c.name for c in result}
    assert "##### BEIN SPORTS #####" not in names


def test_get_all_keeps_normal_channel_alongside_header(repo, channels_with_header) -> None:
    """get_all() keeps real channels that live alongside category-header rows."""
    result = repo.get_all()
    names = {c.name for c in result}
    assert "BEIN SPORTS HD" in names


def test_get_all_excludes_multiple_hash_variants(db_session, repo) -> None:
    """All three header examples from the bug report are excluded."""
    make_channel(db_session, "##### BEIN SPORTS #####")
    make_channel(db_session, "###### RELAX 4K ######")
    make_channel(db_session, "##### BE SPORTS HD ##### · HD")
    make_channel(db_session, "BEIN SPORTS HD", detected_prefix="BEIN")
    db_session.commit()

    result = repo.get_all()
    names = {c.name for c in result}

    assert "##### BEIN SPORTS #####" not in names
    assert "###### RELAX 4K ######" not in names
    assert "##### BE SPORTS HD ##### · HD" not in names
    assert "BEIN SPORTS HD" in names


def test_get_all_single_hash_prefix_not_excluded(db_session, repo) -> None:
    """A channel name with a single leading '#' is NOT a header and must appear."""
    make_channel(db_session, "#1 News")
    db_session.commit()

    result = repo.get_all()
    names = {c.name for c in result}
    assert "#1 News" in names

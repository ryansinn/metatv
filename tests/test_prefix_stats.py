"""Tests for ChannelRepository.get_prefix_stats().

get_prefix_stats() is what populates the filter panel UI.  Wrong counts here
mean the panel shows misleading numbers and the filter state can be broken.
Key invariants:
  - channels_without_prefix + channels_with_prefix == total (non-hidden)
  - channels_without_quality counts channels where detected_quality IS NULL
  - language_groups counts aggregate by group, not by individual prefix
  - quality_groups use detected_quality column (not detected_prefix)
  - unmapped_prefixes are codes not in any lang/platform/region group
"""

import pytest
from tests.conftest import make_channel

LANG_GROUPS = {
    "English": ["EN"],
    "French":  ["FR"],
    "German":  ["DE"],
}
QUAL_GROUPS = {
    "HD":       ["HD", "FHD"],
    "4K / UHD": ["4K", "UHD"],
    "SD":       ["SD"],
}
PLAT_GROUPS = {
    "EAR":     ["EAR"],
    "Netflix": ["NF"],
}
REGION_GROUPS = {
    "North America": ["US", "CA"],
}


@pytest.fixture
def stats_channels(db_session):
    make_channel(db_session, "EN - BBC",       detected_prefix="EN",  detected_quality=None)
    make_channel(db_session, "EN - CNN HD",    detected_prefix="EN",  detected_quality="HD")
    make_channel(db_session, "FR - TF1",       detected_prefix="FR",  detected_quality=None)
    make_channel(db_session, "DE - Das Erste", detected_prefix="DE",  detected_quality="SD")
    make_channel(db_session, "EAR - Dan",      detected_prefix="EAR", detected_quality=None)
    make_channel(db_session, "NF - Squid",     detected_prefix="NF",  detected_quality="4K")
    make_channel(db_session, "GO - Channel",   detected_prefix="GO",  detected_quality=None)  # unmapped
    make_channel(db_session, "Untagged",       detected_prefix=None,  detected_quality=None)
    make_channel(db_session, "Hidden Ch",      detected_prefix="EN",  detected_quality="HD", is_hidden=True)
    db_session.commit()


def get_stats(repo):
    return repo.get_prefix_stats(
        language_groups=LANG_GROUPS,
        quality_groups=QUAL_GROUPS,
        platform_groups=PLAT_GROUPS,
        regional_groups=REGION_GROUPS,
    )


# ── Totals ─────────────────────────────────────────────────────────────────────

def test_total_excludes_hidden(repo, stats_channels):
    stats = get_stats(repo)
    # 8 visible, 1 hidden — total should be 8
    assert stats['total_channels'] == 8


def test_prefix_counts_sum(repo, stats_channels):
    stats = get_stats(repo)
    # channels_with_prefix + channels_without_prefix == total
    assert (stats['channels_with_prefix'] + stats['channels_without_prefix']
            == stats['total_channels'])


def test_channels_without_prefix_count(repo, stats_channels):
    stats = get_stats(repo)
    assert stats['channels_without_prefix'] == 1  # "Untagged"


def test_channels_without_quality_count(repo, stats_channels):
    stats = get_stats(repo)
    # EN-BBC (None), FR-TF1 (None), EAR-Dan (None), GO-Channel (None), Untagged (None) = 5
    assert stats['channels_without_quality'] == 5


# ── Language groups ────────────────────────────────────────────────────────────

def test_language_group_counts(repo, stats_channels):
    stats = get_stats(repo)
    assert stats['language_groups']['English'] == 2  # EN-BBC + EN-CNN HD
    assert stats['language_groups']['French']  == 1
    assert stats['language_groups']['German']  == 1


def test_language_groups_exclude_hidden(repo, stats_channels):
    # Hidden EN channel must not inflate English count
    stats = get_stats(repo)
    assert stats['language_groups']['English'] == 2  # not 3


# ── Quality groups ─────────────────────────────────────────────────────────────

def test_quality_groups_use_detected_quality_column(repo, stats_channels):
    """Quality counts must come from detected_quality, not detected_prefix.

    NF has detected_prefix='NF' but detected_quality='4K'.
    Without this invariant, 4K count would be 0 and NF would appear in quality.
    """
    stats = get_stats(repo)
    assert stats['quality_groups'].get('HD', 0) == 1        # EN-CNN HD
    assert stats['quality_groups'].get('4K / UHD', 0) == 1  # NF-Squid
    assert stats['quality_groups'].get('SD', 0) == 1        # DE-Das Erste
    # Platform prefix NF must not appear as a quality group
    assert 'NF' not in stats['quality_groups']


# ── Platform groups ────────────────────────────────────────────────────────────

def test_platform_group_counts(repo, stats_channels):
    stats = get_stats(repo)
    assert stats['platform_groups'].get('EAR', 0) == 1
    assert stats['platform_groups'].get('Netflix', 0) == 1


# ── Unmapped prefixes ──────────────────────────────────────────────────────────

def test_unmapped_prefixes_are_identified(repo, stats_channels):
    stats = get_stats(repo)
    assert 'GO' in stats['unmapped_prefixes']


def test_known_prefixes_not_unmapped(repo, stats_channels):
    stats = get_stats(repo)
    unmapped = set(stats['unmapped_prefixes'])
    assert 'EN'  not in unmapped
    assert 'EAR' not in unmapped
    assert 'NF'  not in unmapped


def test_prefix_counts_dict(repo, stats_channels):
    stats = get_stats(repo)
    assert stats['prefix_counts']['EN']  == 2
    assert stats['prefix_counts']['FR']  == 1
    assert stats['prefix_counts']['EAR'] == 1
    assert stats['prefix_counts']['GO']  == 1


# ── Additional channel filter tests ───────────────────────────────────────────
# (Placed here to avoid bloating test_channel_filters.py)

def test_invert_prefix_filters_shows_unidentified_only(repo, db_session):
    """invert_prefix_filters=True shows channels NOT in the identity pool.

    Used for the hidden/unidentified workflow — lets users find channels with
    unmapped prefixes without knowing their codes in advance.
    """
    make_channel(db_session, "EN - BBC",    detected_prefix="EN")
    make_channel(db_session, "EAR - Dan",   detected_prefix="EAR")
    make_channel(db_session, "GO - Channel",detected_prefix="GO")
    make_channel(db_session, "AS - Channel",detected_prefix="AS")
    db_session.commit()

    # Identity pool = EN + EAR. Inverted → show GO, AS (not in pool).
    result = repo.get_all(
        language_prefixes=["EN"],
        platform_prefixes=["EAR"],
        invert_prefix_filters=True,
        include_untagged=False,
    )
    result_names = {c.name for c in result}
    assert "GO - Channel" in result_names
    assert "AS - Channel" in result_names
    assert "EN - BBC"     not in result_names
    assert "EAR - Dan"    not in result_names


def test_provider_id_filter(repo, db_session):
    make_channel(db_session, "CH A", detected_prefix="EN", provider_id="prov1")
    make_channel(db_session, "CH B", detected_prefix="EN", provider_id="prov2")
    db_session.commit()

    result = repo.get_all(provider_id="prov1")
    assert len(result) == 1
    assert result[0].name == "CH A"


def test_provider_id_list(repo, db_session):
    make_channel(db_session, "CH A", detected_prefix="EN", provider_id="prov1")
    make_channel(db_session, "CH B", detected_prefix="EN", provider_id="prov2")
    make_channel(db_session, "CH C", detected_prefix="EN", provider_id="prov3")
    db_session.commit()

    result = repo.get_all(provider_id=["prov1", "prov2"])
    assert len(result) == 2


def test_limit_parameter(repo, db_session):
    for i in range(10):
        make_channel(db_session, f"Channel {i}", detected_prefix="EN")
    db_session.commit()

    result = repo.get_all(limit=3)
    assert len(result) == 3


def test_adult_mode_hide(repo, db_session):
    make_channel(db_session, "Safe Channel",  detected_prefix="EN", is_adult=False)
    make_channel(db_session, "Adult Channel", detected_prefix="EN", is_adult=True)
    db_session.commit()

    result = repo.get_all(adult_mode="hide")
    names = {c.name for c in result}
    assert "Safe Channel"  in names
    assert "Adult Channel" not in names


def test_adult_mode_only(repo, db_session):
    make_channel(db_session, "Safe Channel",  detected_prefix="EN", is_adult=False)
    make_channel(db_session, "Adult Channel", detected_prefix="EN", is_adult=True)
    db_session.commit()

    result = repo.get_all(adult_mode="only")
    names = {c.name for c in result}
    assert "Adult Channel" in names
    assert "Safe Channel" not in names

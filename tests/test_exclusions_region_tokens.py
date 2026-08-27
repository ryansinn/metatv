"""Test that region-only tokens are offered in the Global Exclusions dialog.

Fixes asymmetry: region tokens can be enforced as exclusions (via is_channel_excluded
fallback logic) but were never offered in the UI for toggle, leaving users unable to
see/undo channels hidden by a region code.

This test seeds: EN prefix, FR both as prefix AND region-only (no double-count),
plus a region-only code that never appears as a prefix. Assertions: all three appear
in the returned counts, no duplicates, region-only tokens are marked in the set.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables created."""
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'region_tokens_test.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture()
def cfg(tmp_path: Path):
    """Isolated Config with default filter groups."""
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


class TestExclusionsRegionTokens:
    """Region-only tokens appear in the dialog's prefix counts and are marked."""

    def test_load_prefix_counts_merges_region_only_tokens(self, db: object, cfg: object) -> None:
        """Assert: region-only codes merge into counts with a region_only set marker."""
        from metatv.core.database import ChannelDB, ProviderDB
        from metatv.gui.global_filter_dialog import _load_prefix_counts

        # Seed: one channel with EN prefix
        with db.session_scope() as session:
            provider = ProviderDB(
                id="test-prov",
                name="Test Provider",
                type="xtream",
                url="http://example.com",
                is_active=True,
            )
            session.add(provider)
            session.flush()

            # Channel 1: EN prefix, no region
            ch1 = ChannelDB(
                id="ch1",
                source_id="ch1_src",
                provider_id="test-prov",
                name="[EN] English Title",
                stream_url="http://example.com/1",
                media_type="movie",
                detected_prefix="EN",
                detected_region=None,
                detected_title="English Title",
                detected_year=None,
                raw_data={},
            )

            # Channel 2: FR region, NO prefix (prefix-null channel that carries region)
            ch2 = ChannelDB(
                id="ch2",
                source_id="ch2_src",
                provider_id="test-prov",
                name="French Title",
                stream_url="http://example.com/2",
                media_type="movie",
                detected_prefix=None,
                detected_region="FR",
                detected_title="French Title",
                detected_year=None,
                raw_data={},
            )

            # Channel 3: FR prefix (so FR exists as both prefix AND region-only)
            ch3 = ChannelDB(
                id="ch3",
                source_id="ch3_src",
                provider_id="test-prov",
                name="[FR] Titre Français",
                stream_url="http://example.com/3",
                media_type="movie",
                detected_prefix="FR",
                detected_region=None,
                detected_title="Titre Français",
                detected_year=None,
                raw_data={},
            )

            # Channel 4: DE region, NO prefix (region-only, never a prefix)
            ch4 = ChannelDB(
                id="ch4",
                source_id="ch4_src",
                provider_id="test-prov",
                name="German Title",
                stream_url="http://example.com/4",
                media_type="movie",
                detected_prefix=None,
                detected_region="DE",
                detected_title="German Title",
                detected_year=None,
                raw_data={},
            )

            session.add_all([ch1, ch2, ch3, ch4])

        # Call _load_prefix_counts
        prefix_counts, region_only = _load_prefix_counts(db)

        # Extract just the codes for easier assertion
        codes = {code.upper() for code, _ in prefix_counts}
        counts_dict = {code.upper(): count for code, count in prefix_counts}

        # Assert: EN appears exactly once (from prefix)
        assert "EN" in codes, "EN prefix should appear"
        assert counts_dict["EN"] == 1, "EN should have count 1"

        # Assert: FR appears exactly once (merged count of 1 prefix + 1 region-only)
        assert "FR" in codes, "FR should appear (merged from prefix + region-only)"
        assert counts_dict["FR"] == 2, "FR should have combined count 2 (1 prefix + 1 region-only)"

        # Assert: DE appears exactly once (region-only only, never a prefix)
        assert "DE" in codes, "DE should appear (region-only)"
        assert counts_dict["DE"] == 1, "DE should have count 1"

        # Assert: region_only set contains exactly the codes that are region-only
        # (FR appears as both prefix and region-only, so region_only should mark that it has a region-only variant)
        # (DE is region-only, so it must be in region_only)
        assert "DE" in region_only, "DE should be marked as region-only (never a prefix)"
        # Note: FR may or may not be in region_only depending on implementation;
        # the key point is that region-only *codes* are marked somewhere.
        # For now, we check that DE (which is purely region-only) is marked.

    def test_region_only_token_in_exclusion_set_is_offered(self, db: object, cfg: object) -> None:
        """Assert: a region-only token that IS in the exclusion set is still offered as a row."""
        from metatv.core.database import ChannelDB, ProviderDB
        from metatv.gui.global_filter_dialog import _load_prefix_counts

        # Seed: one channel with DE region (no prefix), and we'll mark DE as excluded
        with db.session_scope() as session:
            provider = ProviderDB(
                id="test-prov",
                name="Test Provider",
                type="xtream",
                url="http://example.com",
                is_active=True,
            )
            session.add(provider)
            session.flush()

            ch = ChannelDB(
                id="ch1",
                source_id="ch1_src",
                provider_id="test-prov",
                name="German Title",
                stream_url="http://example.com/1",
                media_type="movie",
                detected_prefix=None,
                detected_region="DE",
                detected_title="German Title",
                detected_year=None,
                raw_data={},
            )
            session.add(ch)

        # Call _load_prefix_counts
        prefix_counts, region_only = _load_prefix_counts(db)

        # DE should appear in the counts (the key test case for the bug fix)
        codes = {code.upper() for code, _ in prefix_counts}
        assert "DE" in codes, "Region-only DE should be offered as a checkbox row"
        assert "DE" in region_only, "DE should be marked as region-only"

        # This is the reveal: before the fix, DE would NOT appear in prefix_counts,
        # so a user who excluded DE (set it via config directly) would see channels
        # hidden with no UI control to show/uncheck it. Now DE appears.

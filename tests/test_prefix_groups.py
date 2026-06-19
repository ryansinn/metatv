"""Tests for the BASE_PREFIX_GROUPS filter-category grouping."""

from metatv.core.config import BASE_PREFIX_GROUPS, Config


def test_adult_prefixes_grouped_together():
    """X, XXX, and ADULT must all live in one 'Adult' group, not surface separately."""
    assert "Adult" in BASE_PREFIX_GROUPS
    assert set(BASE_PREFIX_GROUPS["Adult"]) == {"X", "XXX", "ADULT"}


def test_adult_group_resolves_through_config():
    """The resolved prefix→group mapping (overrides applied) exposes the Adult group."""
    groups = Config().filter_language_groups
    assert "Adult" in groups
    for code in ("X", "XXX", "ADULT"):
        assert code in groups["Adult"], f"{code} should resolve to the Adult group"

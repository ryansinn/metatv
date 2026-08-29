"""Tests for the BASE_PREFIX_GROUPS filter-category grouping."""

from metatv.core.config import BASE_PREFIX_GROUPS, Config


def test_adult_prefixes_grouped_together():
    """X, XXX, and ADULT must all live in one 'Adult' group, not surface separately.

    CONTAINMENT, not equality. This asserted the set was EXACTLY
    ``{"X", "XXX", "ADULT"}``, which made adding a curated code a red gate —
    `PORNBOX` broke it, and the code was correct. The docstring already said
    what the test meant: these three must live together in one group. Whether a
    fourth joins them is a curation decision, not a regression.

    The property that would actually break is asserted below: they are in ONE
    group, not scattered across several.
    """
    assert "Adult" in BASE_PREFIX_GROUPS
    adult = set(BASE_PREFIX_GROUPS["Adult"])
    assert {"X", "XXX", "ADULT"} <= adult, (
        f"the three base adult codes are not all in the Adult group: {adult}"
    )
    others = {
        name: set(codes) for name, codes in BASE_PREFIX_GROUPS.items()
        if name != "Adult"
    }
    for code in ("X", "XXX", "ADULT"):
        stray = [n for n, codes in others.items() if code in codes]
        assert not stray, f"{code} also appears in {stray} — it must live in one group"


def test_adult_group_resolves_through_config():
    """The resolved prefix→group mapping (overrides applied) exposes the Adult group."""
    groups = Config().filter_language_groups
    assert "Adult" in groups
    for code in ("X", "XXX", "ADULT"):
        assert code in groups["Adult"], f"{code} should resolve to the Adult group"

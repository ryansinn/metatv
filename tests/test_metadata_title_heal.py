"""Details pane keeps the clean detected_title when metadata.title is a stale copy.

Regression guard for the #345/#349 interaction: #345 copied the (then-current)
detected_title into metadata.title for provider-fallback rows; #349's mid-name-year
pre-cut then made detected_title cleaner (stripping trailing "(YYYY) CAST"), leaving
those stored metadata.title copies stale. The details pane shows metadata.title, so it
regressed to the raw-looking form. A DB migration heal proved unreliable (a raw UPDATE
races the live app's SQLite lock), so the fix is render-side: keep the clean
detected_title when metadata.title is the "clean base + trailing (YYYY) CAST" pollution.
The detector selects an already-stored field — it never re-parses the name.
"""

from __future__ import annotations

from metatv.gui.details_sections import _is_stale_polluted_title


def test_cast_laden_metadata_titles_are_flagged():
    assert _is_stale_polluted_title(
        "From Dusk Till Dawn",
        "From Dusk Till Dawn 4K (1996) HARVEY KEITEL , TARANTINO, CHEECH MARIN",
    )
    assert _is_stale_polluted_title(
        "Eternal Sunshine Of The Spotless Mind",
        "Eternal Sunshine Of The Spotless Mind (2004) JIM CARREY",
    )
    assert _is_stale_polluted_title("Wicked", "Wicked (2024) BROADWAY MUSICAL")
    # A bare "clean base + (year)" copy is also stale (year shown separately).
    assert _is_stale_polluted_title("Cowboy Bebop", "Cowboy Bebop (1998)")


def test_genuine_titles_are_not_flagged():
    assert not _is_stale_polluted_title("Blade Runner", "Blade Runner")            # equal
    assert not _is_stale_polluted_title("Star Wars", "Star Wars: A New Hope")       # longer, no (year)
    assert not _is_stale_polluted_title("Blade Runner", "Blade Runner 2049")        # bare number, no parens
    assert not _is_stale_polluted_title("Cowboy Bebop", "Bebop Cowboy (1998)")      # not a prefix
    assert not _is_stale_polluted_title("", "Anything (1996)")                      # no clean base

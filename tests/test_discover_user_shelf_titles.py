"""A user-category or recipe shelf's "See all" heading is its own title (D49).

``browse_title_for_key`` fell through to the raw key for ``user_cat:`` and
``recipe:``, so the browse page was headed "user_cat:Comfort Watches". It is
now also what the loader titles those strips with, so the two cannot differ.
"""

from metatv.gui import icons as _icons
from metatv.gui.discover_workers import browse_title_for_key


def test_user_category_heading_is_the_category_name():
    assert browse_title_for_key("user_cat:Comfort Watches") == "Comfort Watches"


def test_recipe_heading_keeps_the_recipe_marker():
    assert browse_title_for_key("recipe:Weeknight Thrillers") == (
        f"{_icons.recipe_icon} Weeknight Thrillers")


def test_no_shelf_namespace_falls_through_to_its_raw_key():
    for key in ("user_cat:X", "recipe:X", "genre:X", "collection:X", "decade:1990"):
        assert ":" not in browse_title_for_key(key).replace(_icons.recipe_icon, ""), key

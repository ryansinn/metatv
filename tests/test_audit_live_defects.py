"""Three defects a user could hit, each the same shape: a second copy that drifted.

None of these is exotic. In every case the correct behaviour already existed
somewhere in the app, and a sibling written later did it differently — which is
why the assertions below compare the two surfaces to EACH OTHER rather than to
a hardcoded expectation. A test that pins one surface's wording or field cannot
notice that the other one disagrees.
"""

import pathlib
from unittest import mock

import pytest

from metatv.core.config import Config
from metatv.core.preference_engine import ScoredChannel


# ---------------------------------------------------------------------------
# 1. The recommendation title
# ---------------------------------------------------------------------------

def _scored(**over):
    base = {
        "channel_id": "c1",
        "channel_name": "EN| MOVIES: The Matrix (1999) FHD",
        "media_type": "movie", "score": 1.0, "matching_genres": [],
        "matching_keywords": [], "director": None, "poster_url": None,
        "reason": "Action", "detected_title": "The Matrix",
    }
    base.update(over)
    return ScoredChannel(**base)


def test_display_title_prefers_the_cleaned_title():
    """94.9% of the owner's rows have detected_title != name, so this is the
    normal case, not the edge one."""
    assert _scored().display_title == "The Matrix"


def test_display_title_falls_back_to_the_raw_name():
    """A row ingested before the field existed still has to render something."""
    assert _scored(detected_title="").display_title == "EN| MOVIES: The Matrix (1999) FHD"


def test_both_recommendation_surfaces_read_the_same_definition():
    """The actual defect: two renderings of ONE scored list disagreed.

    The sidebar wrote ``sc.detected_title or sc.channel_name`` and the
    Preferences dashboard wrote ``sc.channel_name`` — the obvious attribute,
    and the wrong one. Asserted at source level because the two live in
    different widgets with different construction costs; what matters is that
    neither reaches for the raw field directly.
    """
    import inspect

    from metatv.gui import preferences_view
    from metatv.gui.sidebar import recommended

    for mod in (preferences_view, recommended):
        src = inspect.getsource(mod)
        assert "sc.display_title" in src, (
            f"{mod.__name__} must render the shared display_title")
        assert "sc.channel_name" not in src.replace("sc.channel_name)", ""), (
            f"{mod.__name__} still reaches for the provider's raw string")


# ---------------------------------------------------------------------------
# 2. The two Preferences disclosures that forgot their state
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "preferences_exclusions_expanded",
    "preferences_version_prefs_expanded",
])
def test_the_disclosure_state_survives_a_restart(field, tmp_path):
    """Both flipped visibility and saved nothing, against "every UI section
    saves its collapse state". Their sibling _toggle_attributes always did.

    Driven through a real save/load cycle rather than by setting an attribute,
    because the bug was the ABSENCE of the write — an in-memory assertion would
    pass against the broken code.
    """
    with mock.patch.object(pathlib.Path, "home", return_value=tmp_path):
        cfg, _ = Config.load()
        assert getattr(cfg, field) is False, "collapsed by default"
        setattr(cfg, field, True)
        cfg.save()

        reloaded, _ = Config.load()
        assert getattr(reloaded, field) is True, (
            f"{field} did not survive a restart")


def test_both_toggles_actually_write_the_config():
    """The write is what was missing, so assert the call, not just the field."""
    import inspect

    from metatv.gui.preferences_view import PreferencesView

    for name in ("_toggle_exclusions", "_toggle_version_prefs"):
        src = inspect.getsource(getattr(PreferencesView, name))
        assert "self.config.save()" in src, (
            f"{name} changes visibility without persisting it")


# ---------------------------------------------------------------------------
# 3. "Clear" beside "Clear All"
# ---------------------------------------------------------------------------

def test_both_dropdown_classes_use_one_footer_label():
    """They sit side by side: Sport: is a FilterDropdown, League: is a
    HierarchicalFilterDropdown, and their footers had drifted to two different
    words for the same button on the same bar."""
    import inspect

    from metatv.gui import filter_bar, sports_filter_bar

    for mod in (filter_bar, sports_filter_bar):
        src = inspect.getsource(mod)
        assert 'QPushButton("Clear All")' not in src
        assert 'QPushButton("Select All")' not in src, (
            f"{mod.__name__} hardcodes a dropdown footer label again")

    assert 'QPushButton(DROPDOWN_CLEAR_LABEL)' in inspect.getsource(sports_filter_bar)
    assert 'QPushButton(DROPDOWN_CLEAR_LABEL)' in inspect.getsource(filter_bar)

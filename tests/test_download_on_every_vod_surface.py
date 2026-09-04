"""Download must be offered wherever a VOD row can appear.

It shipped on the channel list alone. The registry was found and exactly one of
nine entries was filled, so a movie in Favorites, History, the Watch Queue,
Recommendations, Discover or a Recipe had no way to download it — while the
same movie in the search results did.

These tests are DERIVED from the registry, not from a hand-written list of
surfaces. A hand-written list is the same mistake one level up: it cannot see a
surface nobody remembered to add to it. The exclusions are named explicitly
with their reasons, so adding a tenth surface fails until someone decides which
side it is on.
"""

from __future__ import annotations

import pytest

from metatv.gui.channel_menu import ACTIONS, SURFACE_LAYOUTS

#: Surfaces that deliberately do NOT offer download, and why.
NO_DOWNLOAD = {
    "retry": "a stream that failed to open — downloading it fails the same way",
    "epg_on_now": "live programmes, not VOD",
    "epg_browse": "live programmes, not VOD",
}

#: Surfaces that deliberately do NOT offer record, and why.
NO_RECORD = {
    "epg_browse": "record() records what is on NOW; this browses FUTURE "
                  "programmes, so it would record the wrong thing (REC-3)",
    "retry": "a stream that failed to open",
    "history": "VOD", "favorites": "VOD", "queue": "VOD",
    "recommended": "VOD", "alerts": "VOD",
}


def _vod_surfaces() -> list[str]:
    return [s for s in SURFACE_LAYOUTS if s not in NO_DOWNLOAD]


@pytest.mark.parametrize("surface", _vod_surfaces())
def test_every_vod_surface_offers_download(surface):
    """The rule: unless there is a stated reason, a VOD row can be downloaded."""
    assert "download" in SURFACE_LAYOUTS[surface], (
        f'"{surface}" shows VOD rows but has no download entry. Either add it '
        f"or add {surface!r} to NO_DOWNLOAD with the reason.")


def test_the_exclusions_are_real_surfaces():
    """Non-degeneracy: a typo'd exclusion would silently excuse a real surface.

    Without this, renaming a surface turns its exclusion into a no-op AND drops
    it from the parametrised list above — the check would pass by covering
    nothing.
    """
    for name in list(NO_DOWNLOAD) + list(NO_RECORD):
        assert name in SURFACE_LAYOUTS, (
            f"{name!r} is excluded but is not a surface — stale after a rename")


def test_download_is_gated_to_vod_not_by_the_layout():
    """Listing it everywhere is only safe because the action gates itself.

    If `applies` stopped checking media_type, every live channel in Favorites
    would offer a download that cannot work.
    """
    from types import SimpleNamespace

    applies = ACTIONS["download"].applies

    def ctx(media_type):
        return SimpleNamespace(is_single=True, channel_found=True,
                               media_type=media_type, programme_start=None)

    assert applies(ctx("movie")) is True
    assert applies(ctx("series")) is True
    assert applies(ctx("live")) is False, (
        "download is no longer VOD-gated — it would now render on live rows "
        "across every surface it was just added to")


@pytest.mark.parametrize("surface", [s for s in SURFACE_LAYOUTS if s not in NO_RECORD])
def test_every_live_surface_offers_record(surface):
    assert "record" in SURFACE_LAYOUTS[surface], (
        f'"{surface}" shows live rows but has no record entry.')


def test_record_is_gated_to_live():
    from types import SimpleNamespace

    applies = ACTIONS["record"].applies

    def ctx(media_type):
        return SimpleNamespace(is_single=True, channel_found=True,
                               media_type=media_type, programme_start=None)

    assert applies(ctx("live")) is True
    assert applies(ctx("movie")) is False


def test_every_listed_action_has_a_handler_in_the_shared_builder():
    """A menu entry with no handler is a dead click.

    Adding an action to five layouts is only safe because _build_handlers
    returns one dict for every surface. This asserts download and record are in
    it, so the additions above cannot render as no-ops.
    """
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "metatv" / "gui" / "main_window_channels.py").read_text()
    for action in ("download", "record"):
        assert f'"{action}": lambda' in source, (
            f"{action} is listed in a layout but has no handler — a dead click")

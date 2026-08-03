"""What's New entry for extending live theme-switch coverage to the six
previously-restart-only content views (EPG, Discover, Recipe, Preferences/
Recommended, Provider editor, Sources manager)."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=261,
    title="Switching themes now live-restyles the EPG, Discover, Recipe, "
          "Preferences, Provider editor, and Sources manager views",
    items=(
        "These six full-window views used to need an app restart (or at "
        "least leaving and reopening) to fully pick up a new theme — each "
        "gained its own live theme refresh, matching the middle filter "
        "column and details pane.",
        "EPG: the header separator, stale-guide notice, and every "
        "Watchlist/My-Channels/Discover/On-Now/Browse/Events tab's static "
        "labels and stats footers now restyle instantly.",
        "Discover: the zoom icon, Manage button, loading label, More "
        "Categories button, and the shared \"Show all\" browse drill-down "
        "now restyle instantly.",
        "Recipe: the facet-overview header/back button, the sub-tab bar, "
        "the one-line recipe bar, the Matching Content shelf, the tag "
        "cloud, the cluster grid, and the Saved tab all restyle instantly.",
        "Preferences/Recommended: the movie/series mix controls and the "
        "Excluded/Version-Preferences collapsible toggles restyle instantly.",
        "Provider editor and Sources manager: the header fields, action "
        "bar, footer, icon picker, and the Sources list's empty-state "
        "message all restyle instantly, including when the editor is "
        "embedded inside the Sources manager.",
    ),
    version="0.24.0",
    date="2026-08-02",
    test_steps=(
        "Open Settings → Interface → Appearance, switch to Daylight while "
        "the EPG view (any tab) is open — the stale-guide notice border/text "
        "and every tab's muted labels/stats line switch to light-theme "
        "colors immediately, no restart needed.",
        "While on Daylight, open Discover — the zoom icon, Manage button, "
        "and (if shown) the loading/More-Categories chrome are light-themed "
        "immediately.",
        "While on Daylight, open the Recipe tab — the facet header/back "
        "button, the RECIPE bar, the Matching Content shelf header, and the "
        "tag cloud header/controls are light-themed immediately; switch to "
        "the Saved tab and confirm its title/subtitle/empty-hint are too.",
        "While on Daylight, open Preferences/Recommended — the \"Mix\" "
        "caption, mix label, Automatic button, and the Excluded/Version "
        "Preferences toggles are light-themed immediately.",
        "While on Daylight, open Sources → select a source to open the "
        "Provider editor — the Icon/Provider Name field labels, action-bar "
        "buttons, footer, and icon picker are light-themed immediately; "
        "deselect all sources so the \"Select a source…\" empty state shows "
        "and confirm it is light-themed too.",
        "Switch back to Midnight — all six views match their original "
        "appearance exactly, no leftover Daylight styling.",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=207,
    version="0.18.0",
    date="2026-08-01",
    title="EPG data hygiene + smarter watchlist ranking",
    items=(
        "EPG guide data now self-prunes: after every successful guide fetch, "
        "programmes that expired more than a day ago (configurable) are "
        "swept out across ALL sources — including a source that has stopped "
        "refreshing — so the EPG table no longer grows unbounded.",
        "Gzip-compressed XMLTV guide feeds (a common provider format) now "
        "parse correctly instead of failing; detection is automatic (magic "
        "bytes, .gz URL, or a Content-Encoding: gzip header) and a corrupt "
        "gzip stream degrades to a partial guide instead of losing the fetch.",
        "Settings → Metadata & API Keys → EPG gained two controls that were "
        "previously config-file-only: \"Notify before show\" (5-120 minutes) "
        "and \"Auto-refresh guides on launch and interval\".",
        "Browse's \"Hide Filler\" toggle now actually persists across "
        "restarts (it only seeded its initial state before) and its label "
        "reflects whether hiding is currently on.",
        "Watchlist cards now rank channels within each show match by quality "
        "(4K > FHD > HD > SD) and previously-watched-first, so the 3-per-show "
        "display cap keeps your best streams instead of an arbitrary subset.",
        "Each watchlist card gained a \"Show all in Search\" link that jumps "
        "straight to Search pre-filled with that card's pattern.",
    ),
    test_steps=(
        "Open Settings → Metadata & API Keys → EPG → set 'Notify before show' "
        "to 30 minutes and toggle 'Auto-refresh guides' off → Save → reopen "
        "Settings → both values persisted.",
        "Open EPG → Browse → click 'Hide Filler' to toggle it off → switch to "
        "another tab and back (or restart) → the toggle stays off and the "
        "button label reflects it ('Hide Filler', no checkmark).",
        "Open EPG → Watchlist with a tracked show airing on multiple "
        "channels of different quality → the 4K/best channels appear before "
        "SD/lower-quality ones in the card.",
        "Click 'Show all in Search' on any watchlist card → the app switches "
        "to the channel list with Search active and the query pre-filled "
        "with that card's pattern.",
        "If any of your sources use a gzip-compressed XMLTV guide URL, "
        "trigger a manual EPG refresh for it → the guide populates instead "
        "of showing an EPG parse error.",
    ),
)

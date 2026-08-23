from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=339,
    version="0.41.0",
    date="2026-08-23",
    title="One header across the top, and the bottom bar is gone",
    items=(
        "The five view buttons sat in a bar pinned to the bottom edge of the "
        "window — roughly 950 pixels away from the content they switch. They "
        "now live in a header across the top, alongside the app name and "
        "search.",
        "The header reads left to right: MetaTV, the search box, the five "
        "views, then Split, Tools and Exclusions.",
        "Search moved up there too. It is the main way into a library this "
        "size, so it now sits in the same place on every screen rather than "
        "being buried in the results area.",
        "Diagnose lost its permanent button — a niche action that was pinned "
        "on screen next to the primary navigation forever. It is in the new "
        "Tools menu, with the rest of the diagnostics.",
        "The whole bottom bar is gone, which gives its height back to the "
        "content.",
        "The menu bar stays exactly where it is.",
    ),
    test_steps=(
        "Launch the app → a header runs across the top with MetaTV at the "
        "left, then the search box, then the five view buttons; the bottom "
        "bar is gone entirely.",
        "Click each of Search / EPG / Recommended / Discover / Recipe → the "
        "view changes and the active button fills its cell in the track.",
        "Type in the header search box while on Search → the channel list "
        "filters exactly as it did before.",
        "Switch to EPG or Discover → the search box hides (it filters the "
        "channel list, so it would do nothing there); switch back to Search "
        "→ it returns.",
        "Click Tools → the menu opens with Diagnostics, Filters and "
        "'Diagnose stream quality' among the entries; run 'Diagnose stream "
        "quality' on a selected channel and confirm it still works.",
        "Toggle Split → it lights when on, exactly as it did in the bottom "
        "bar; open Exclusions from the header → the dialog opens and the "
        "count on the chip is right.",
        "Check the File / View / Style / Layout / Buffer / Tools / Help menu "
        "bar is still there and still works.",
        "Switch theme through Midnight, Graphite and Daylight → the header "
        "restyles with the rest of the app.",
    ),
)

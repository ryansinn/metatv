from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=183,
    version="0.14.2",
    date="2026-07-31",
    title="EPG status + Refresh moved to a persistent bottom bar",
    items=(
        "The source-freshness status text and the Refresh button no longer sit "
        "in the EPG tab header — they moved to a slim, right-aligned bar along "
        "the bottom of the EPG view, shown on every tab. The whole header width "
        "now belongs to the tab bar.",
        "The Browse \"###,### programmes\" count shares that same bottom line "
        "(on the left), so status, Refresh and the count all read as one status "
        "strip. The count blanks out on the other EPG tabs.",
    ),
    test_steps=(
        "Open the EPG view → the source status text (e.g. 'TREX Shared · Updated "
        "18h ago') and the Refresh button appear right-aligned on a bottom bar, "
        "NOT in the tab header.",
        "Switch to the Browse tab → the '###,### programmes' count shows on the "
        "left of that same bottom line, with status + Refresh still on the right.",
        "Switch to another EPG tab (e.g. On Now) → the Refresh button and status "
        "text stay visible on the bottom bar and the programmes count blanks out.",
        "Click Refresh on the bottom bar → EPG data refreshes for the active "
        "sources and the status text updates (same behaviour as before).",
    ),
)

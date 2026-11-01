from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=796,
    version="0.232.0",
    date="2026-11-01",
    title="Hide live events that haven't started yet",
    items=("A new Global Exclusions switch, on by default: \"Hide live events that start after the next "
           "source refresh\". Event slots for games further away than that show only a black screen until "
           "kickoff, and the source re-reads them at its next refresh. The row shows when that is.",
           "Empty event slots with no game scheduled (VICTORY+, VIX, SN+, MLS PPV placeholders dated 2098) "
           "are hidden by the same switch. Applied on the next launch.",
           "Prefer a fixed window? Pick \"more than [N] [minutes … years] in the future\"; \"Sync to source "
           "refresh\" puts it back.",),
    test_steps=("Launch MetaTV, open Exclusions — \"Hide live events that start [after the next source "
                "refresh]\" is checked and names the next refresh date and time.",
                "Search \"Victory+\" — no empty slots like \"(Victory+ 002)\".",
                "Choose \"hours\" and 24 — \"Sync to source refresh\" appears; OK, then search an event "
                "collection — only games within 24 hours show.",
                "Uncheck the switch, OK — upcoming games and empty slots come back.",),
)

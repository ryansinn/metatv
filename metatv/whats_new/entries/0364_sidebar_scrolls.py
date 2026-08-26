from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=364,
    version="0.41.0",
    date="2026-08-26",
    title="Sidebar sections show everything and scroll",
    items=(
        "Sidebar sections now show every entry and scroll, like any other "
        "list. They used to show only what fit and hide the rest, which meant "
        "a section holding two hundred entries looked exactly like one holding "
        "three.",
        "If your pointing device cannot scroll, Settings → Interface → Sidebar "
        "has \"Use 'Show N more' rows instead of scrollbars\": sections then "
        "show what fits and end with a row that makes the section taller.",
        "One switch, both halves — you always get a scrollbar or a way to "
        "reveal more, never a truncated list with neither.",
    ),
    test_steps=(
        "Open a sidebar section with more entries than fit → every entry is "
        "there and the section has a scrollbar. Scroll it normally.",
        "Check History with a long viewing history → it now loads far more "
        "than the 30 entries it used to stop at.",
        "Settings → Interface → Sidebar → tick \"Use 'Show N more' rows "
        "instead of scrollbars\" → OK. Sections lose their scrollbars and end "
        "with a \"Show N more\" row instead; clicking it makes the section "
        "taller.",
        "Untick it → the scrollbars come back and every entry is visible "
        "again.",
    ),
)

"""What's New entry for the honest EPG empty state and the source-editor URL
field moving above the list it feeds, with a plain-language TV-guide explainer."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=269,
    title="The TV guide says why it's empty, and adding a URL is where you'd look for it",
    items=(
        "An empty TV guide always said the same thing: \"No EPG sources\". "
        "That covered four different situations — you have no sources at all, "
        "your sources don't publish a guide, you switched the guide off, or "
        "everything is set up and it just hasn't downloaded yet. Only the last "
        "one is fixed by pressing Refresh, so the other three sent people "
        "hunting for a fault that wasn't there.",
        "Each case now says what is actually true and what to do about it — "
        "and the guide only suggests Refresh when refreshing would help.",
        "In the source editor, the box for adding a URL sat BELOW the list of "
        "URLs it fills. A tester pasted addresses into the list instead, which "
        "is the reasonable thing to do when the list is the big obvious target "
        "and the real input is underneath it. The input is now above the list.",
        "The EPG section is titled \"TV guide (EPG)\" and opens with a plain "
        "explanation of what a guide gives you and why you'd leave it on, "
        "rather than assuming you already know what EPG and XMLTV mean.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "With no sources configured, open the EPG view — the status line reads "
        "\"No sources yet\" and suggests adding one, instead of \"No EPG "
        "sources\". The EPG chip stays clickable either way.",
        "Add a source but turn its TV guide OFF (Sources → pick it → Settings "
        "→ TV guide). Reopen EPG: it says the guide is turned off and points at "
        "the setting — and does NOT tell you to press Refresh, which could not "
        "help.",
        "Turn the guide back on without fetching. EPG now says the guide isn't "
        "downloaded yet and points you at Refresh Guide — the one case where "
        "Refresh is the answer.",
        "Open Sources → pick a source → Connection. The \"Paste a URL here…\" "
        "box sits ABOVE the list of existing URLs. Type one and press Enter — "
        "it appears in the list below.",
        "Open the Settings tab of the same source: the section is headed \"TV "
        "guide (EPG)\" and starts with a short plain-language explanation.",
    ),
)

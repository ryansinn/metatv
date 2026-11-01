from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=774,
    version="0.210.0",
    date="2026-10-31",
    title="Event times and prefixes the name parser was missing",
    items=("Pay-per-view events dated like \"Mon 26 Oct 01:00 EDT\" now show their start time, "
           "including ones with a numeric zone such as \"+03\" or \"-02\". About 480 of them "
           "were sorted into no list and had no time.",
           "A title filed under a genre prefix such as \"WESTERN-DE\" is tagged with that genre.",
           "Source Analytics' Unrecognized prefixes list now leaves out what the parser already "
           "knows: event statuses (LIVE, NEXT, END, ENDED), TV, BLURAY, MULTI, AFR, genres, and "
           "prefixes made of known parts such as BLURAY-DE or UK-NOWTV. What's left is grouped "
           "into live channels, films and series.",),
    test_steps=("Refresh a source that carries PPV events (TREX), then open Sports/PPV — events "
                "written \"ENDED | … | Mon 26 Oct 01:00 EDT (US) | …\" are listed with their "
                "start time.",
                "Find a \"WESTERN-DE - …\" film after the refresh — its tags include Western.",
                "Open Sources → TREX → Analytics → Unrecognized prefixes — LIVE, NEXT, ENDED, TV, "
                "BLURAY-DE, WESTERN-DE, UK-NOWTV, AFR and MULTI are absent, and the list has "
                "Live channels / Films / Series headings with a count each.",),
)

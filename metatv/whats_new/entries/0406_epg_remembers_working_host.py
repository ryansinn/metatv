from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=406,
    version="0.53.0",
    date="2026-08-28",
    title="The guide URL now points at a server that actually answers",
    items=(
        "A source can list many servers, and not all of them serve a TV guide. "
        "When fetching the guide the app already tried them in turn until one "
        "worked - but it never remembered which one did.",
        "So the guide address it showed you, and checked against, was always "
        "whichever server happened to be listed first. On a source with twenty "
        "servers that address could return 'Forbidden' forever while the actual "
        "fetch was quietly succeeding somewhere else.",
        "That is why the guide could show an error next to a green "
        "'AUTODETECTED' badge and never change.",
        "The server that last delivered a guide is now remembered and used "
        "first, so the address you see is one known to work. Only the server is "
        "remembered - your username and password are still read fresh every "
        "time, so changing your subscription still takes effect immediately.",
        "If you remove that server from the source, it is forgotten and the app "
        "goes back to trying the rest.",
    ),
    test_steps=(
        "Open a source with several servers and look at the EPG guide URL in "
        "its settings.",
        "Refresh the guide. If the first server does not serve one, the "
        "displayed address should change to the server that did.",
        "Confirm the guide loads and programmes appear in the EPG view.",
        "Change the source's username or password and confirm the guide URL "
        "picks up the new credentials on the next refresh.",
        "Remove the remembered server from the source's server list and confirm "
        "the guide still fetches rather than getting stuck.",
    ),
)

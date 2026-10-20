from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=,
    version="0.193.0",
    date="2026-10-20",
    title="Fewer duplicate genres and regions in the filters",
    items=("Genres a provider writes in Arabic or Persian, or several to a string "
           "(\"Comedy طنز اجتماعی\", \"Comedy | Drama | Romance\"), now count under the "
           "genres they name, so Drama and Comedy are one row each instead of dozens. "
           "Only obvious matches are folded; anything unclear keeps its own row.",
           "A country listed under several codes is one row in Region: ticking Israel "
           "selects both IL and ISR. Hindi, Tamil, Telugu and other language codes "
           "now appear under Language, not Region.",
           "Existing libraries are tidied once, in the background, at the next launch."),
    test_steps=("Launch, let 'Tidying duplicate genre and region labels' finish, then open "
                "the Genre filter — no Arabic or Persian Drama/Comedy rows remain beside "
                "Drama and Comedy.",
                "Open the Region filter — Israel (and Argentina, Denmark…) appears once; "
                "ticking it shows channels from every code the country uses.",
                "Open the Language filter — Hindi is listed there, and no longer under Region."),
)

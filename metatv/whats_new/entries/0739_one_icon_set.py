from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=739,
    version="0.176.0",
    date="2026-10-19",
    title="One icon set: hearts for favourites, a bookmark for Watch Later",
    items=("Favourites are marked with a heart instead of a star (stars now mean ratings), "
           "Watch Later is a bookmark, and the sidebar's \"something new\" marker is a bell "
           "with a dot. This is the first step of moving every icon in the app to one "
           "consistent set; more screens follow.",),
    test_steps=("Open a title's right-click menu or the details pane — the favourite control "
                "shows a heart (outline when not a favourite, filled when it is).",
                "Find a Watch Later control (channel right-click → Watch Later) — it shows a "
                "bookmark, not an eye.",
                "With unseen Watch Alerts, the sidebar header shows a bell with a dot."),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=633,
    version="0.103.0",
    date="2026-09-08",
    title="Discover gets a shelf per streaming platform",
    items=(
        "Discover now rolls your library up by the platform a title came from: "
        "a Netflix shelf, a Disney+ shelf, and one for every other platform "
        "your sources carry enough of. They sit after your own category and "
        "recipe shelves, and each one leads with what that platform added most "
        "recently.",
        "\"Enough\" is yours to set — Settings ▸ Content ▸ Discover shelves. A "
        "platform earns a shelf once at least this many DISTINCT TITLES carry "
        "its tag (50 by default). Titles, not copies: a film your sources hold "
        "in six qualities counts once, and shows on the shelf once.",
        "Movies and series only. Live channels never appear on these shelves — "
        "\"what did Netflix add\" and \"what is on now\" are different "
        "questions, and Discover answers the first.",
        "Four tags that look like platforms but are not never get a shelf: the "
        "two catch-all buckets (\"Other Streaming\", \"Pay TV\") and the two "
        "subtitle libraries (\"SC\", \"EAR\"). Splitting those into real "
        "brands needs better parsing and is its own job.",
    ),
    test_steps=(
        "Open Discover and scroll past your category and recipe shelves → a "
        "shelf named for each streaming platform that clears the threshold "
        "(on a large library: Netflix, Disney+, Apple TV+).",
        "Settings ▸ Content ▸ Discover shelves → lower \"A platform gets a "
        "shelf at\" to 15, click OK → Discover rebuilds and more platform "
        "shelves appear. Raise it back to 50 → they go away again.",
        "Scan a platform shelf for live channels → there are none; every card "
        "is a movie or a series.",
        "Look for an \"Other Streaming\" shelf → there is never one, however "
        "much content carries that tag.",
        "Find a title your sources carry in several qualities on a platform "
        "shelf → it appears exactly once, not once per copy. Click \"See all\" "
        "on the shelf → the browse header reads the platform's name.",
    ),
)

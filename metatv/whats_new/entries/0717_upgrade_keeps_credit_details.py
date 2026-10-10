from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=717,
    version="0.157.0",
    date="2026-10-10",
    title="Upgrading an old library keeps character names and billing order",
    items=("A very old library's one-time tag-table rebuild kept dropping each credit's "
           "character name and billing order; it now carries them across.",
           "Clearing the details pane also hides its Details section and the "
           "'Get stream details' button."),
    test_steps=("Open a movie's details, then pick a category with no titles so the pane "
                "clears — no 'Details for …' heading or 'Get stream details' button is left "
                "behind.",),
)

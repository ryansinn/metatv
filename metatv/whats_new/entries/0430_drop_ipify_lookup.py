from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=430,
    version="0.54.0",
    date="2026-08-29",
    title="The app no longer asks an outside service for your IP address",
    items=(
        "Whenever a source URL failed, the app quietly contacted a third-party "
        "website to look up your public IP address.",
        "It was there to spot an IP that a provider had blocked - a genuinely "
        "useful idea - but it never worked: not one of the 280 recorded "
        "attempts had an address stored, so nothing ever read it.",
        "The lookup is gone. Failures are still recorded exactly as before.",
    ),
    test_steps=(
        "Add a source with a deliberately wrong URL and let it fail. Confirm "
        "the failure is still recorded against that URL.",
        "Confirm the source's reliability score still changes with successes "
        "and failures.",
    ),
)

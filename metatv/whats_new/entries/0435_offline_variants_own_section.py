from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=435,
    version="0.54.0",
    date="2026-08-29",
    title="A source you turned off is no longer offered as somewhere to watch",
    items=(
        "Also Available listed versions from sources you had disabled. They "
        "looked slightly dimmer and the tooltip admitted the source was "
        "inactive, but they sat among the ones you can actually play.",
        "They were counted too - the header could read 3 versions when only 2 "
        "were available.",
        "Those versions now appear under their own Offline Sources heading, "
        "and the count only reflects what you can watch.",
        "They are still there and still clickable, because right-clicking one "
        "offers to reactivate the source and play it. That recovery route is "
        "the reason they are shown at all.",
        "Offline Sources is a separate section from Filtered Variants on "
        "purpose. Filtered Variants holds things your own filters set aside, "
        "and expanding it should never reveal content from a source you "
        "switched off.",
    ),
    test_steps=(
        "Turn off one source, then open a title that exists on both it and an "
        "active source. Confirm Also Available lists only the active version "
        "and the count matches what is listed.",
        "Confirm an Offline Sources heading appears below, and expanding it "
        "shows the version from the disabled source.",
        "Right-click that offline chip and confirm the reactivate-and-play "
        "option is still offered.",
        "Open a title that has no offline versions and confirm the Offline "
        "Sources heading is absent rather than empty.",
        "Open a title with offline versions, then another without, and confirm "
        "no chips from the first title remain.",
    ),
)

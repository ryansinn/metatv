from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=96,
    version="0.9.0",
    date="2026-06-28",
    title="Details: Watched toggle in the action rail + live channel logo in the poster",
    items=(
        "Movies and series now have a Watched (✓) toggle in the details action rail, "
        "directly above Hide. It glows when watched and dims when unwatched — click it "
        "to mark watched/unwatched. This replaces the old '✓ Watched' text line.",
        "The Watched toggle persists through the same path as the right-click "
        "'Mark as Watched' action, so the channel list updates in place.",
        "Live channels now show their channel LOGO in the poster space (contained, not "
        "stretched) instead of an empty area; the category/country line stays beneath it. "
        "Channels without a logo fall back to the header as before.",
    ),
    test_steps=(
        "Open a MOVIE you have NOT watched. Confirm a dim checkmark (✓) Watched button "
        "appears in the action rail just above the Hide button; hover it to see "
        "'Mark as watched'. Confirm there is no '✓ Watched' text line under the metadata.",
        "Click the Watched toggle. Confirm it lights up (checked), its tooltip becomes "
        "'Mark as unwatched', and the title shows the watched indicator in the channel "
        "list. Re-open the title and confirm the toggle is still lit (persisted).",
        "Click it again to unmark. Confirm it dims and the channel-list watched indicator "
        "clears.",
        "Select a SERIES and confirm the Watched toggle also appears; select a LIVE "
        "channel and confirm the Watched toggle is NOT shown.",
        "Open a LIVE channel that has a logo. Confirm its logo appears in the poster area "
        "(reasonably sized, not stretched to full poster height) with the category/country "
        "line beneath it.",
        "Open a LIVE channel with no logo and confirm the poster area is hidden (header "
        "fallback). Switch from a live channel to a movie and confirm the movie poster "
        "loads at full size (the live-logo box doesn't shrink it).",
    ),
    addresses=("flagged:2f783519-5801-4911-ab0c-e5bd9fe5b29a",),
)

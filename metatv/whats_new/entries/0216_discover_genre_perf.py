from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=216,
    version="0.18.1",
    date="2026-08-01",
    title="Discover genre shelves expand instantly (were 15-20 seconds)",
    items=(
        "Expanding or pinning a genre shelf in Discover — e.g. 'Sci-Fi & "
        "Fantasy' — used to take 15-20 seconds with no feedback at all, the "
        "shelf just sat empty. Genre is now computed once when your library "
        "is ingested and stored, so opening a shelf reads a small indexed "
        "field instead of re-scanning your whole catalog's raw provider data "
        "on every click. A one-time background pass backfills this for your "
        "existing library on first launch after updating.",
        "Any shelf that's still loading (genre or otherwise) now shows a "
        "'Loading…' row the instant you expand or pin it, and a clear error "
        "row if the fetch fails — instead of silently sitting empty either way.",
    ),
    test_steps=(
        "Open Discover, expand a collapsed genre shelf like 'Sci-Fi & "
        "Fantasy' — cards appear within about a second, with a 'Loading…' "
        "row visible briefly while they load.",
        "Pin a different collapsed genre shelf from the Manage dialog — it "
        "moves to the top and its cards load quickly, same as expanding.",
        "Confirm a multi-genre title (e.g. one tagged 'Action & Adventure / "
        "Sci-Fi' by your provider) still shows up under both its genre "
        "shelves, matching what it showed before this change.",
    ),
)

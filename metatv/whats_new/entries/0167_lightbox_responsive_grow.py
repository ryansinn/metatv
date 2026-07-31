from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=167,
    version="0.11.0",
    date="2026-07-30",
    title="Similar Titles lightbox — bigger, responsive card with no forced scroll",
    items=(
        "The Similar Titles preview card is now generous and sizes itself to the "
        "window: it grows wider on a large window (up to a readable maximum) instead "
        "of staying a small fixed box in the middle.",
        "The card also grows to fit its content, so the poster, Overview, Cast & "
        "Crew, Other Versions and the Similar Titles strip are all visible at once "
        "on a normal large window — the internal scrollbar now appears only when the "
        "window is genuinely too short to show everything.",
        "No more empty dead-space at the bottom of the card: it hugs its content and "
        "the layout matches the approved design's proportions and spacing.",
    ),
    test_steps=(
        "Maximize (or use a large) MetaTV window, open a movie/series with metadata, "
        "and open its Similar Titles preview lightbox (the ⤢ button on a Similar "
        "row): the card is large and fills a generous share of the window — not a "
        "small centred box.",
        "In that preview on a large window, confirm the poster, Overview, Cast & "
        "Crew, Other Versions and the horizontal Similar Titles strip are ALL "
        "visible in one frame with NO internal scrollbar.",
        "Shrink the MetaTV window to be short, reopen the preview: now a vertical "
        "scrollbar appears (content genuinely exceeds the window) — and it "
        "disappears again once the window is tall enough.",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=164,
    version="0.11.0",
    date="2026-07-30",
    title="Similar Titles preview lightbox — poster hero, real ratings, Other Versions",
    items=(
        "The similar-titles preview got a full redesign: a poster hero with the "
        "title, rating, runtime and source, an Overview and Cast & Crew, an "
        "\"Other Versions\" row and a scrollable \"Similar Titles\" strip — all in "
        "one overlay you can browse without leaving the details pane.",
        "Every Similar row now has a small ⤢ button: click it to open the preview "
        "lightbox for that title (right-clicking the name still works too).",
        "Like / Dislike / Not-Interested now light up to match the title's real "
        "saved state — previously the preview always showed them blank because it "
        "read the wrong place.",
        "The \"Other Versions\" row and the \"×N versions\" badge read the stored "
        "content identity, so every language/quality copy of the same title is one "
        "click away — and, like Similar Titles, versions from disabled or expired "
        "sources are never shown.",
        "Browse with the ‹ › chevrons (or ← →), dive into any similar title or "
        "version, step Back with Backspace, and close with Esc. The poster is a "
        "static preview for now, sized as the future in-place player.",
    ),
    test_steps=(
        "Open a movie/series with metadata in the details pane and scroll to "
        "\"Similar Titles\": each row shows a ⤢ button. Click it → the preview "
        "lightbox opens showing that title's poster, rating/runtime/type, source, "
        "Overview and Cast.",
        "On a title you've rated (👍 or 👎) or marked Not-Interested, open its "
        "preview: the matching rating button is lit (not blank).",
        "Pick a title that exists on more than one source (e.g. \"12 Monkeys\"): "
        "the meta line shows a \"×N versions\" badge and an \"Other Versions\" row "
        "lists each version tagged by source; a version on a disabled/expired "
        "source never appears there. Click a version → the lightbox navigates to it.",
        "Use the ‹ › chevrons (or ← / →) to step through the similar list; click a "
        "card in the \"Similar Titles\" strip (or its ⤢) to dive in — a Back "
        "control appears; press Backspace to go back, then Esc to close.",
    ),
)

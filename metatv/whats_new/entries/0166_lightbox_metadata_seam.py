from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=166,
    version="0.11.0",
    date="2026-07-30",
    title="Similar Titles preview now shows full details for every title",
    items=(
        "The Similar Titles preview lightbox used to come up nearly blank — no "
        "poster, plot, cast, genres or rating — for most titles, because it only "
        "showed details that happened to be cached already (a tiny fraction of your "
        "library).",
        "It now loads the title's details on demand through the same path the "
        "details pane uses, so the preview card fills in with poster, overview, "
        "cast, genres and rating even for a title you've never opened before. The "
        "result is cached, so opening it again is instant.",
        "The scrollable Similar Titles strip stays fast — its cards keep their "
        "lightweight name/year/poster and are not fetched one-by-one on every open.",
    ),
    test_steps=(
        "Open a movie or series you have NOT viewed in the details pane before, "
        "scroll to \"Similar Titles\", and click the ⤢ button on one of the rows: "
        "the preview lightbox card now shows a poster, an Overview (plot), Cast & "
        "Crew, genre chips and a rating — where before it was blank.",
        "Close and reopen the same preview: it appears instantly (the fetched "
        "details are cached).",
        "In an open preview, browse the \"Similar Titles\" strip at the bottom: the "
        "cards show name/year and a poster where available and scroll smoothly "
        "without a per-card loading delay.",
    ),
)

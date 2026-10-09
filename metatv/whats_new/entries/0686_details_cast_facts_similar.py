from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=686,
    version="0.132.0",
    date="2026-10-09",
    title="Cast as chips, Details by where each fact came from",
    items=(
        "Cast is a Director row and a Cast row of clickable chips; people you "
        "like or dislike carry ▲/▼.",
        "Tags and Technical Details are replaced by 'Details for <copy>' — "
        "facts grouped as From <source> / From TMDb / Yours / In the title / "
        "Guessed, each guess saying why.",
        "Similar titles shorten with … instead of running under the year.",
    ),
    test_steps=(
        "Select a film with cast — Cast shows Director and Cast rows of chips; "
        "click one and the list filters to that person.",
        "Open 'Details for …' — the heading names the copy (e.g. English (EN)); "
        "facts sit under FROM <your source>, FROM TMDB, GUESSED etc.; a guessed "
        "language is dashed with 'from region …' beside it; Released shows the date.",
        "Click a fact chip — the list filters to that tag; right-click — Discover opens.",
        "Find a Similar title longer than the pane — it ends in … and the year "
        "stays visible; click it — the preview lightbox opens.",
        "Sections run Available in, Overview, Cast, Details, Similar with tight spacing.",
    ),
)

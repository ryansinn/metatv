from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=169,
    version="0.13.0",
    date="2026-07-31",
    title="Similar Titles: click the title to preview — no more ⤢ button",
    items=(
        "Clicking a title in the details-pane 'Similar Titles' list now opens the "
        "preview lightbox directly, instead of replacing the details pane. Your "
        "anchor title stays put, so you never lose the source you were exploring "
        "from — close the lightbox and you land right back where you started.",
        "The small ⤢ preview button on every Similar row is gone — it was clutter "
        "and an extra step. The row itself is the trigger now.",
        "Still want to fully switch to a similar title (its own details pane, season "
        "tree, resume, and all)? Right-click it — that opens it in the details pane.",
    ),
    test_steps=(
        "Open a movie/series with metadata and scroll to 'Similar Titles': confirm "
        "the rows no longer show a ⤢ button.",
        "Left-click a similar title's name: the preview lightbox opens on that title "
        "while the details pane behind it still shows your original (anchor) title. "
        "Press Esc — you are back on the original title, nothing was replaced.",
        "Right-click a similar title's name: it opens in the full details pane "
        "(replacing the current one) — the deliberate 'commit to this title' action.",
    ),
)

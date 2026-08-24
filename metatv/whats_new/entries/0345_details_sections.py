from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=345,
    version="0.41.0",
    date="2026-08-24",
    title="Every details section folds away, and says how much it holds",
    items=(
        "Overview and Also available can now be collapsed. They were the two "
        "sections that could not be — not by choice, but because collapsing "
        "one meant writing a fifth copy of the same toggle code.",
        "All six sections remember whether you left them open, independently, "
        "across restarts.",
        "Counts moved to the right-hand end of the header where the eye "
        "expects them: Cast shows its number, Also available shows "
        "\"65 versions · 19 regions\", Similar titles shows its count instead "
        "of carrying it inside the title as \"Similar Titles (18)\".",
        "The whole header is the click target now, not just the small chevron "
        "— the words toggle the section too.",
        "Similar titles gained a ⤢ that opens the full preview overlay, so "
        "the pane can show a handful and still offer the way to all of them.",
    ),
    test_steps=(
        "Open a movie in the details pane → Overview, Also available, Cast, "
        "Technical details, Tags and Similar titles each show a chevron.",
        "Click the WORD \"Overview\" (not the chevron) → the section folds "
        "away. Click it again → it comes back.",
        "Collapse Overview and Cast, then click a different channel and back "
        "→ both are still collapsed.",
        "Quit and relaunch → Overview and Cast are still collapsed; expand "
        "them, quit and relaunch → they are still expanded.",
        "On a title with many versions → \"Also available\" shows "
        "\"N versions · M regions\" at the right of its header, and collapsing "
        "it hides the region chips.",
        "On a title with cast → the Cast header shows the number of people at "
        "the right.",
        "Similar titles → the count sits at the right of the header, and "
        "clicking the ⤢ beside it opens the preview overlay on the first title.",
        "Collapse a section, then switch to a live channel and back to a movie "
        "→ the section is still collapsed and no other section changed.",
    ),
)

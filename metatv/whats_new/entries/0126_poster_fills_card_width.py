from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=126,
    version="0.9.0",
    date="2026-06-29",
    title="Details poster fills the card cleanly — no side padding, no rapid-nav resize glitch",
    items=(
        "The details-pane poster now FILLS the width of its card. Before, a normal "
        "portrait (2:3) poster was fit inside a fixed-height box, so on a wider pane it "
        "ended up narrower than the card and showed grey side padding that wouldn't go "
        "away (most noticeable on Cowboy Bebop).",
        "Fixed the resize glitch where paging quickly through a title's variants left the "
        "poster scaled too wide: the poster used to be sized before the layout settled. "
        "It now re-fits to the final width after each change, so rapid navigation no "
        "longer leaves a stretched/oversized poster.",
        "Live channel logos are unchanged — they still sit centered in the poster area "
        "(a logo shouldn't be blown up to fill the card).",
    ),
    test_steps=(
        "Open a movie/series with a normal portrait poster (e.g. Cowboy Bebop) and widen "
        "the details pane: the poster fills the card width with NO grey side padding at "
        "any width.",
        "Page rapidly up and down through a title's variants (arrow keys): the poster "
        "stays correctly sized — it never ends up stretched too wide.",
        "Drag the pane narrower and wider: the poster re-fits to the new width each time, "
        "always filling it with no side gaps.",
        "Open a LIVE channel that has a logo: the logo is still centered in the poster "
        "area (not stretched to fill).",
    ),
)

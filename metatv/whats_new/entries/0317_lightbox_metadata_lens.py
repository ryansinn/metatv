"""What's New entry: cast, crew and genres in the preview lightbox are now
clickable, opening that person's or genre's titles inside the overlay rather
than filtering the channel list hidden behind it."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=317,
    title="Cast, crew and genres in the preview are now clickable",
    items=(
        "In the preview overlay, Cast & Crew was a dead line of text and the "
        "genre chips did nothing — the same names and genres have been "
        "clickable in the details pane all along.",
        "Clicking a name or a genre now re-seeds the preview with that "
        "person's or genre's titles, and you can page through them with the "
        "same arrows. It deliberately does NOT filter the list behind the "
        "overlay: that list is out of sight, so a click there would change "
        "something you can't see and cost you the trail you walked.",
        "Back (or Backspace) leaves the lens and puts you exactly where you "
        "were, and the breadcrumb shows the thread — \"Adaptation. › With "
        "Nicolas Cage › Con Air\". Lenses nest, so you can keep going.",
        "When you do want the full list, \"See all in Search\" appears in the "
        "preview's header next to the lens name; it closes the preview and "
        "filters the channel list, landing on the same titles the lens was "
        "showing.",
        "A person is matched the way the rest of the app matches one: the "
        "enriched cast/director, the title itself (so a provider's \"NICOLAS "
        "CAGE COLLECTION\" channel counts), and the raw source data. Titles "
        "from disabled or expired sources, hidden rows, and anything your "
        "Global Exclusions cover stay out, and repeat copies of one film "
        "collapse to a single entry.",
        "Found while checking the above: the preview is a dark \"cinema\" panel "
        "in every theme, but most of its colours were being picked for the "
        "theme's own background. On Daylight that left the Back button "
        "invisible, turned the poster wells and keyboard hints into white "
        "boxes, and hid the state glyphs on the similar strip. The panel now "
        "has its own fixed set of colours, and every one of them is measured "
        "against the surface it actually paints on.",
    ),
    version="0.32.0",
    date="2026-08-21",
    test_steps=(
        "Open a movie's details pane, click a Similar Titles row to raise the "
        "preview overlay, then click an actor's name under CAST & CREW — the "
        "preview re-seeds with that actor's other titles, the header reads "
        "\"With <name>\", and the trail above it shows where you came from.",
        "With the lens open, use the ← → arrows (or the chevrons) to page "
        "through that actor's titles — the counter reads \"1 of N\".",
        "Press Backspace (or click Back) — you land back on the exact title "
        "you clicked the name from, with its own similar set restored.",
        "Click a genre chip in the preview instead — same behaviour, with the "
        "header reading \"<Genre> titles\".",
        "Open a lens, then click \"See all in Search\" in the header — the "
        "preview closes and the channel list shows a \"Cast/Crew: <name>\" "
        "(or \"Genre: <genre>\") chip listing the same titles.",
        "Click a name that appears in only one title you own — a line under "
        "the header says \"Nothing else with <name>\" and the preview stays "
        "where it is instead of navigating nowhere; it clears as soon as you "
        "navigate.",
        "Switch to the Daylight theme (Style menu) and open the preview — the "
        "Back button, the keyboard hints along the bottom, and the poster "
        "placeholders are all legible on the dark panel, exactly as in "
        "Midnight; nothing renders as a white box.",
        "Inside a lens, check the bottom hint line — it reads \"browse these "
        "results\" rather than \"browse similar\", because the arrows are "
        "paging the lens, not the anchor's similar titles.",
    ),
)

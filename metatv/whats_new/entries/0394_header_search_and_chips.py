from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=394,
    version="0.51.0",
    date="2026-08-27",
    title="The view switcher stops jumping, and hovering it does something",
    items=(
        "The search box used to vanish whenever you left the Search view, "
        "which shoved the view switcher 250 pixels sideways - the control you "
        "use to change views moved because you changed views. The box now "
        "stays put on every view.",
        "Because it is always there, it now does something everywhere: type "
        "anything and press Enter and you land in Search with that query "
        "already run.",
        "Hovering a view button used to paint it the same colour as the "
        "background behind it, so it vanished rather than lit up - on every "
        "dark theme the hover was actually darker than the button. It now "
        "gets an accent outline, a faint accent tint and brighter text: "
        "clearly interactive, without pretending to be the selected one.",
    ),
    test_steps=(
        "Click through Search, EPG, Recommended, Discover and Recipe - the "
        "row of view buttons must not shift sideways at any point.",
        "On any view except Search, type a title into the header search box "
        "and press Enter - you should land in Search with results.",
        "Press Enter in an EMPTY search box on another view - nothing should "
        "happen; it must not yank you to Search for no query.",
        "Hover each unselected view button - it should gain a visible outline "
        "and brighter text, and must not fade into the background.",
        "Check the hovered label does not shift by a pixel as the pointer "
        "crosses it.",
        "Repeat the hover check on Gruvbox, Gruvbox Light and Daylight - this "
        "was reported on Gruvbox but measured wrong on every dark theme.",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=625,
    version="0.103.0",
    date="2026-09-07",
    title="Headings, carets, dialog buttons and progress bars all match now",
    items=(
        "Favorites and Watch Queue group headings are drawn the same way as "
        "every other sidebar section's — a quiet small-caps label with the "
        "count carrying the emphasis. Favorites' headings now carry a count "
        "at all, which they never did.",
        "Every collapse/expand caret in the app is the same glyph. Five "
        "different ones were in use, including the list-ordering ▲/▼ arrows "
        "standing in for a fold, which mean \"move this\", not \"open this\".",
        "Hover any of those carets and it says what it opens — \"Expand "
        "Plot\", \"Collapse Nordic\" — instead of \"Expand this section\", "
        "which was true of seven headers at once and identified none of them.",
        "Every dialog's row of buttons is built the same way and Enter always "
        "presses the obvious one. About and the Stream Diagnostics dialogs had "
        "no proper button row at all, so their Close button sat wherever the "
        "layout left it.",
        "Progress bars match: the same height, trough and corners everywhere, "
        "with colour reserved for saying what is progressing — orange for a "
        "resume position, green or red for a preference weight, the "
        "subscription hue for time left on an account.",
    ),
    test_steps=(
        "Open the sidebar's Favorites and Watch Queue sections — each group "
        "heading reads as small-caps grey text with a brighter count beside "
        "it, exactly like History's and Downloads' headings.",
        "Type into the Watch Queue's find box — the headings change to show "
        "\"N of M\" beside the label, and clearing the box restores the plain "
        "count.",
        "Open a movie's details pane and hover the caret beside Plot, then "
        "Cast — the tooltip names that section (\"Collapse Plot\") and flips "
        "to \"Expand Plot\" after you click it.",
        "In the details pane's Other Versions section, expand Filtered "
        "variants — its header caret is the same shape as the section header "
        "above it and its text is one size smaller, not the same size.",
        "Open Help ▸ About and press Escape — it closes. Reopen it: there is "
        "a Close button at the bottom right with Copy details beside it, and "
        "Enter closes the dialog.",
        "Open a stream's diagnostics from the status bar and press Escape — "
        "it closes; the Close button sits at the bottom right, with Apply "
        "tuning & Save away to the left.",
        "Open Settings — OK, Cancel and Apply are all still there, Apply next "
        "to OK rather than off on its own, and Enter presses OK.",
        "In Discover, find a card for something you part-watched — the thin "
        "orange strip along the bottom of its poster is still there and still "
        "shows how far you got.",
        "Open Sources ▸ edit a source and look at the Remaining bar — it is "
        "the same height as the bars in Preferences, and its colour still "
        "changes with how long is left.",
        "Switch to the Daylight theme with any of those bars on screen — the "
        "filled part stays clearly visible against the empty part.",
    ),
)

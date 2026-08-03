from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=264,
    version="0.24.0",
    date="2026-08-02",
    title="Add Source button now clearly visible",
    items=(
        "The 'Add Source' (+) button on the Sources sidebar strip is now prominently visible: 28×24 pixels, bright text on a colored background, with a clear border.",
        "The 'Add Source' button in the Sources manager view now shows the full label '+ Add Source' with adequate padding and sizing.",
        "First-time users with no sources can now easily find the way to add a source.",
    ),
    test_steps=(
        "Sidebar (Sources section): Look at the header row with 'Sources' title — the + button (far right) should be clearly visible and easy to click (bright/not faded).",
        "Sources Manager view (main area): Click the + button to open Add Source — it should say '+ Add Source' in full text and be easy to spot.",
        "Verify both buttons still trigger the 'Add Source' dialog correctly when clicked.",
    ),
)

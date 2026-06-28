from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=75,
    version="0.8.0",
    date="2026-06-28",
    title='Variant chips now show details on click (not play)',
    items=(
        'Left-clicking an "Also available as:" chip now opens that variant\'s details in the'
        " details pane instead of immediately starting playback.",
        "To play a variant directly, right-click its chip and choose"
        ' "Play … version" or "Reactivate source & play" from the menu.',
    ),
    test_steps=(
        'Find a channel that shows "Also available as:" chips in the details pane.'
        " Left-click one chip — the details pane should switch to show that variant's"
        " info without starting playback.",
        "Right-click the same chip → choose \"Play … version\" → that variant's stream"
        " should start playing.",
        "For an inactive-source chip (dimmed): left-click should still show details;"
        " right-click → \"Reactivate source & play\" should activate the source and play.",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=446,
    version="0.56.0",
    date="2026-08-29",
    title="Adult content now has a control, and an empty list says why",
    items=(
        "Adult content was hidden by default and there was no way to change "
        "it. The control existed in the code but was built hidden, and the "
        "line that would have shown it was never called by anything.",
        "Settings now has a Content section holding it: show everything, hide "
        "adult content (the default, unchanged), or show only adult content.",
        "The visible symptom was worse than the missing switch. Opening a "
        "category whose channels are all flagged - PornBox, or the For Adults "
        "collection - returned nothing under the message \"try a different "
        "search\", blaming your search for a gate you had never been shown.",
        "An empty list now names that gate: \"28 hidden as adult content - "
        "change in Settings\", and clicking it opens the setting.",
        "It opens the setting rather than quietly lifting it for one view, "
        "which is what the other four filter notices do. Those are filters you "
        "can trip by accident; this one is a choice you made, so the app hands "
        "you the switch instead of flipping it.",
    ),
    test_steps=(
        "Open Settings and confirm a Content section sits between Interaction "
        "and Recommendations, showing Adult content set to Hide adult content.",
        "With it on Hide, open a category made up of adult-flagged channels "
        "and confirm the list shows a '... hidden as adult content - change in "
        "Settings' bar rather than 'try a different search'.",
        "Click that bar and confirm Settings opens on the Content section.",
        "Set it to Show everything, click OK, and confirm the channels appear "
        "without needing a restart.",
        "Change a filter, restart the app, and confirm the setting is still "
        "Show everything rather than reverting to Hide.",
    ),
)

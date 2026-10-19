from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=751,
    version="0.188.0",
    date="2026-10-19",
    title="Header, EPG record column and remaining buttons use the same clean icons",
    items=("The header's Split and Tools buttons, the EPG trees' Rec column (record, "
           "recording, scheduled), the Sources page, Add filter, See all, Show all, the "
           "Keyboard Shortcuts menu entry and window, Discover's Back link and the "
           "Hide watched checkbox show the app's one icon set instead of emoji. A liked "
           "actor's trend icon no longer makes the cast row jump on macOS.",),
    test_steps=("Look at the header — Split and Tools each show a line icon before the word.",
                "Open the EPG guide — each programme's Rec column shows a record icon; a "
                "programme being recorded shows it in red.",
                "On macOS, open a movie whose cast includes an actor you've liked — the cast "
                "row does not change height when the trend icon appears."),
)

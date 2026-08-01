from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=187,
    version="0.15.0",
    date="2026-07-31",
    title="Cleaner titles everywhere, not just the details pane",
    items=(
        "Titles that had picked up a raw channel name (e.g. "
        "'EN - Cowboy Bebop (1998)') are cleaned to just the title "
        "('Cowboy Bebop'). The language and year are already shown separately, "
        "so they are no longer duplicated in the title itself.",
        "This is a one-time data cleanup that runs automatically on launch, so "
        "every surface that reads the stored title — the details pane, cards, "
        "and lists — shows the clean name. Real provider/TMDb titles are left "
        "exactly as they are.",
        "New titles are cleaned at the source too, so the raw name can no longer "
        "creep back in.",
    ),
    test_steps=(
        "Launch the app once so the one-time cleanup runs. Open the details pane "
        "for a title whose channel name carried a language prefix and a year "
        "(e.g. 'EN - Cowboy Bebop (1998)'). Confirm the big title now reads the "
        "clean 'Cowboy Bebop', with the language chip and year shown separately "
        "beside it (not duplicated in the title).",
        "Open a title that DOES have a real metadata/TMDb match and confirm its "
        "proper metadata title still displays unchanged (genuine titles are not "
        "stripped).",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=234,
    version="0.20.0",
    date="2026-08-02",
    title="Settings redesigned as a three-panel layout",
    items=(
        "The Settings dialog's flat row of tabs is now a left-hand section "
        "list (Playback, Interaction, Recommendations, Metadata & API Keys, "
        "Interface — same five, same order) next to the controls, with a new "
        "right-hand panel that explains what the selected section does.",
        "The dialog remembers its size and which section you last had open, "
        "and restores both the next time you open Settings.",
    ),
    test_steps=(
        ("Open Settings (gear icon or sidebar footer) → a left-hand list of "
         "5 sections appears next to the controls, with a short help blurb "
         "on the right that changes as you click each section.",
         "settings:playback"),
        "Resize the Settings dialog and switch to a different section, then "
        "click OK. Reopen Settings → it comes back at the same size on the "
        "same section.",
        ("Deep-link into Settings on the Interface section (e.g. from the "
         "dev QA checklist) → the Interface section is selected on open.",
         "settings:interface"),
    ),
)

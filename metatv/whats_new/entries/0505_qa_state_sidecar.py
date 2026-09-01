from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=505,
    version="0.65.0",
    date="2026-09-01",
    title="Developer test-checklist data left the settings file",
    items=(
        "The dev testing checklist kept its record inside your settings file, "
        "where it had grown to well over a third of it — and every setting "
        "MetaTV saved, anywhere, rewrote all of that record too.",
        "It now lives in its own file next to your settings. Nothing is lost: "
        "an existing checklist is moved across the first time MetaTV saves, "
        "and if you have never used the dev checklist no extra file appears.",
    ),
    test_steps=(
        "Open MetaTV normally and confirm your settings are all as you left "
        "them.",
        "With METATV_DEV=1, open the Testing Checklist and confirm your "
        "previous ticks, flagged items and notes are still there.",
        "Tick a step, restart, and confirm it is still ticked.",
        "Change a setting, click OK, restart, and confirm both the setting "
        "and the checklist survived.",
    ),
)

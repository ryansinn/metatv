from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=419,
    version="0.53.0",
    date="2026-08-29",
    title="Quitting the app no longer crashes",
    items=(
        "Closing the app could end in a crash instead of a clean exit.",
        "On the way out it stopped the background work of four screens by "
        "name, and only if that screen was on display - but twelve screens "
        "run background work, and an off-screen one is exactly the case that "
        "matters.",
        "Anything still loading was then thrown away mid-run, which is a hard "
        "crash rather than an error.",
        "Every screen is now stopped on the way out, on display or not, and "
        "the app waits for work already in progress before closing the "
        "database underneath it.",
    ),
    test_steps=(
        "Open Discover, switch to another view, then quit. The app should "
        "exit cleanly with no crash message in the terminal.",
        "Start a large search or refresh and quit while it is still running.",
        "Quit immediately after launch, before anything has finished loading.",
    ),
)

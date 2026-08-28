from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=408,
    version="0.53.0",
    date="2026-08-28",
    title="Tools now has 'Open config folder'",
    items=(
        "Settings, logs and the record of which one-time setup passes have run "
        "all live in a folder the app never offered a way to reach.",
        "When something goes wrong the answer is usually in there - but finding "
        "it meant being told a hidden path and going looking.",
        "Tools now opens that folder in your file manager. config.yaml and the "
        "logs are both in it.",
        "If no file manager answers - a minimal desktop, a remote session - it "
        "shows you the path instead of doing nothing.",
    ),
    test_steps=(
        "Open Tools and choose 'Open config folder'. Your file manager should "
        "open on a folder containing config.yaml and a logs folder.",
        "Confirm the file itself is not opened in a text editor - the folder is "
        "what should appear.",
        "Open it a second time and confirm it behaves the same.",
    ),
)

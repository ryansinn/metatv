from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=416,
    version="0.53.0",
    date="2026-08-28",
    title="The macOS build stops failing on a runaway background thread",
    items=(
        "Roughly a third of recent builds failed before producing anything to "
        "download - 19 of the last 60.",
        "The QA checklist window starts a background thread that asks git "
        "about every What's New entry, one at a time. It had no stop path, so "
        "it was still running when the window went away.",
        "A background thread destroyed while running kills the whole process "
        "outright, which is what was happening.",
        "The thread now stops when asked, and closing the window waits for it. "
        "The problem grew with every entry added, so it would only have gotten "
        "worse.",
    ),
    test_steps=(
        "Open the QA checklist window (dev mode) and close it immediately. It "
        "should close at once, with no freeze and no crash.",
        "Open it, let the PR references finish loading, then close it again.",
        "Confirm the entry headers still show their PR number and commit.",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=91,
    version="0.9.0",
    date="2026-06-28",
    title="Testing Checklist: flagged items resolve themselves once a PR addresses them",
    items=(
        "Flagged items that a later PR claims (via an entry's "
        "addresses=(\"flagged:<id>\") declaration) now auto-file into a collapsed "
        "'✓ Resolved' sub-section. The active Flagged Items list shows only what "
        "still needs work — you never have to re-read fixed flags or manually mark "
        "them done.",
        "The Flagged Items count reflects only active (unaddressed) items.",
        "Confirmed already-fixed flagged items are linked here so they file "
        "themselves on this build: new flags appear at the top of the list, the "
        "Archived section sits below Flagged Items, the checklist no longer jumps "
        "to the top when you mark a step failed, and Re-test captures a fresh log.",
    ),
    test_steps=(
        "Open the Testing Checklist (METATV_DEV=1). Confirm a collapsed "
        "'✓ Resolved (N)' group appears below the active Flagged Items list, and "
        "that previously-fixed flags (new-at-top, archive-order, no-jump-on-fail, "
        "re-test-log) are inside it — NOT in the active list.",
        "Confirm the 'Flagged Items (N)' count equals the number of ACTIVE "
        "(unaddressed) items only — resolved items are excluded from it.",
        "Expand '✓ Resolved' and confirm each item shows an 'Addressed PR #…' "
        "badge; collapse it again and confirm the state persists after reopening "
        "the window.",
        "Add a new flagged item and confirm it appears at the TOP of the active "
        "list (not the bottom) and is never auto-filed as resolved.",
    ),
    addresses=(
        "flagged:2952ac81-fd0f-4864-b4ba-bf3aa444f256",  # new flags appear at top
        "flagged:084a75ea-bc59-4127-b7e9-50099ba68d80",  # Re-test captures fresh log
        "flagged:5939c980-0430-4951-bc84-ecbe706e3271",  # Archived sits below Flagged
        "flagged:3fe95093-cd26-4433-ade8-2000fbd17fa2",  # no jump-to-top on mark-fail
    ),
)

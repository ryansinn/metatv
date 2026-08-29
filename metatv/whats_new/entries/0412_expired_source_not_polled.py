from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=412,
    version="0.53.0",
    date="2026-08-28",
    title="An expired source is no longer contacted in the background",
    items=(
        "When a subscription expires the app already hides its content - it "
        "does not appear in results, Similar Titles or the preview.",
        "It kept contacting it anyway. Guide refreshes and new-episode checks "
        "still ran against it, and because every one of that source's twenty "
        "servers refuses an expired account, each attempt worked through all "
        "twenty before giving up.",
        "One expired subscription produced hours of continuous network "
        "requests that could never succeed, and the app was noticeably slow "
        "the whole time.",
        "Background work now uses the same rule the rest of the app already "
        "uses to hide the content. A source that is expired, switched off or "
        "removed is not contacted at all.",
        "A series you follow on more than one source keeps being checked on "
        "the ones that still work.",
        "Separately, a round of checks will no longer start while the previous "
        "one is still running.",
    ),
    test_steps=(
        "With an expired source configured, watch the log - there should be no "
        "guide or episode requests to it at all.",
        "Confirm your working sources still refresh their guides and still "
        "report new episodes.",
        "Follow a series available on two sources, expire one, and confirm new "
        "episodes are still detected on the other.",
        "Confirm the app feels responsive while background checks run.",
    ),
)

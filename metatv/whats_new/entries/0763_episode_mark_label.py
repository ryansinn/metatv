from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=763,
    version="0.200.0",
    date="2026-10-26",
    title="Episode menu reads correctly again",
    items=("Right-clicking an episode showed \"Mark as Unwatched{label_suffix}\" instead of "
           "\"Mark as Unwatched\". It now reads normally, and with several episodes selected "
           "it says how many, e.g. \"Mark as Watched (3 episodes)\".",),
    test_steps=("Open a series, right-click a watched episode — the menu says \"Mark as "
                "Unwatched\" with no {label_suffix} text.",
                "Ctrl-click three unwatched episodes and right-click one — the menu says "
                "\"Mark as Watched (3 episodes)\"; choose it and all three get the ✓.",),
)

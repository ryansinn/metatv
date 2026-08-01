from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=204,
    version="0.17.0",
    date="2026-08-01",
    title="Queue and favorite individual episodes",
    items=(
        "The Watch Later button now works while you're looking at a single "
        "episode — it queues THAT episode instead of drilling into the whole "
        "series, and its tooltip names the episode (e.g. \"Add S02E04 to Watch "
        "Queue\").",
        "The Favorites star does the same in episode view: it favorites the "
        "episode you're looking at, not the series.",
        "Queued and favorited episodes show up in their sidebar sections as "
        "\"Series — S02E04  Title\" rows — double-click plays that episode "
        "directly.",
        "Right-click an episode in the series tree for a new Favorite/Unfavorite "
        "Episode action.",
        "Any button that still acts on the whole series while you're viewing an "
        "episode (Like, Dislike, Not Interested, Hide) now says so in its "
        "tooltip, so nothing is silently series-wide.",
    ),
    test_steps=(
        "Open a series, click into an episode, then click the Watch Later "
        "button — the button's tooltip names the episode (e.g. \"Add S01E01 to "
        "Watch Queue\") and the Watch Queue sidebar shows a new "
        "\"Series — S01E01  Title\" row.",
        "Double-click that queued-episode row in the Watch Queue sidebar — it "
        "plays the episode directly (not the series overview).",
        "With an episode open in the details pane, click the Favorites star — "
        "the Favorites sidebar gains a \"Series — S01E01  Title\" row; clicking "
        "the star again removes it.",
        "Right-click an episode row in the series tree — a Favorite Episode "
        "(or Unfavorite Episode, if already favorited) action appears and "
        "toggles correctly.",
        "With an episode open, hover the Hide button — the tooltip clarifies it "
        "hides the whole series, not just the shown episode.",
    ),
)

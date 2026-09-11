from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=669,
    version="0.121.0",
    date="2026-09-11",
    title="\"Nothing is playing\" waits until the player has actually given up, "
          "and a stream that plays is never left marked as failed",
    items=(
        "The status-bar/toast verdict used to fire at 40 seconds while the "
        "player was still retrying a busy source — which can take close to a "
        "minute — so it announced failure on streams that then went on to "
        "play. It now waits until the player's own retries are exhausted "
        "before saying anything.",
        "Every one of those false verdicts also counted as a play failure; "
        "six of them was enough to hide a title as \"dead\". A stream that "
        "plays now clears its failure record, however it looked a moment "
        "earlier.",
        "The background re-check of previously failed streams no longer "
        "opens a connection to your source while a player window is open — "
        "on a one-connection source that second connection was competing "
        "with the one you were actually watching.",
    ),
    test_steps=(
        "Play a title on a source that's slow to answer — the status bar "
        "should count \"Waiting for <source>…\" past 40s without \"Nothing is "
        "playing\" while the player is still trying, and the title plays.",
        "After it plays, open the Watch Queue's failed-streams section — the "
        "title must not be listed there and its row must not be greyed.",
        "With a player window open, the failed-streams re-check (Watch Queue "
        "-> retry section) must not run on its own; close the player and it "
        "resumes on its normal schedule.",
    ),
)

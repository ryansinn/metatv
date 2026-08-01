from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=190,
    version="0.15.0",
    date="2026-07-31",
    title="Movies can finally appear in Recommendations (their genres are backfilled)",
    items=(
        "Movies were missing from Recommendations because every movie's metadata had "
        "empty genres — the provider's movie LIST only carries name/poster, not genre "
        "(only series lists include genre inline). Recommendations score on genres, so "
        "a genreless movie always scored 0 and never surfaced.",
        "A background pass now fetches each movie's own detail record (the same "
        "get_vod_info call the app already made) and harvests its real genres (plus "
        "plot / cast / director when missing) into the movie's metadata — filling only "
        "empty fields, never overwriting anything you've edited.",
        "It runs off the UI thread, throttled and in batches, and is capped per launch "
        "so a large library is filled over a few launches. Existing libraries are "
        "backfilled automatically — no need to re-add your sources. New movies get "
        "genres through the same path as you browse.",
    ),
    test_steps=(
        "On a library with movies, open a few movies' details so they have metadata "
        "rows, then relaunch and leave the app running ~1 minute → open a movie's "
        "details and confirm its Genres row is now populated (it was empty before).",
        "Open Recommendations (once you have some ratings/favorites) → movies now appear "
        "alongside series, matched on their newly-filled genres (previously the list was "
        "series-only).",
        "Re-open the same movie's details and, if you had manually set/edited any "
        "metadata field, confirm the backfill did NOT overwrite it — only previously "
        "empty fields were filled.",
    ),
)

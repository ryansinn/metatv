from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=69,
    version="0.9.0",
    date="2026-06-24",
    title="Tag backfill migration runs ~10× faster",
    items=(
        "The full tag re-tag migration (triggered when a new tagging version ships) "
        "now batches all DB writes for an entire 500-channel chunk into three SQL "
        "statements instead of ~1 000 individual round-trips. On large libraries "
        "(500k–1M channels) this cuts migration time from 10–40 minutes to under "
        "5 minutes on typical hardware.",
        "User-curated tags (manually added via the UI) are fully preserved — only "
        "machine-generated tags are refreshed.",
    ),
    test_steps=(
        "Trigger a full tag re-tag migration: open ~/.config/metatv/config.yaml, "
        "set tag_backfill_version to 0, save, and relaunch the app. Watch the "
        "'Migration in progress' panel — confirm it completes noticeably faster "
        "than before (especially on a library with many channels).",
        "After the migration completes, open a channel's details pane and verify "
        "its tags (genre, region, quality, etc.) are intact and correct.",
        "Before triggering the migration, manually add a tag to a channel via the "
        "UI (source='user'). After the migration, confirm that user tag still "
        "appears on the channel alongside the refreshed generated tags.",
    ),
)

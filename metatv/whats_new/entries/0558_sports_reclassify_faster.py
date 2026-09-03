"""Sports reclassification now 60x faster: stat() the definitions file once per second instead of per row."""

from metatv.whats_new.entry import WhatsNewEntry

ENTRY = WhatsNewEntry(
    title="Sports reclassify stops stat()ing the definitions file per row (PERF-18)",
    description=(
        "A sports reclassification pass (triggered by provider refresh) used to "
        "call stat() on the override definitions file 785,163 times, one per row. "
        "Within a 1-second TTL, the check is now cached, reducing that to ~100 "
        "syscalls per pass and making the entire pass ~60× faster. A Settings edit "
        "still lands within a second, which no caller can observe."
    ),
    test_steps=(
        ("Go to Browse → Sports", "View displays sports channels"),
        (
            "Trigger a provider refresh (Settings → Sources → Refresh)",
            "The refresh completes without the per-row file-check overhead; "
            "sports and league tags are unchanged"
        ),
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=558,
    version="0.86.0",
    date="2026-09-03",
    title="Sports reclassification stops re-checking a file per row",
    items=(
        "A sports reclassification pass (fired by a provider refresh) called "
        "stat() on the sports-definitions override file once per row — "
        "785,163 syscalls of pressure per pass. The check now holds for one "
        "second at a time, so a pass makes a handful of checks instead.",
        "A Settings edit to your sports definitions still takes effect within "
        "a second — nothing observable changes except the speed.",
    ),
    test_steps=(
        "Refresh a provider with sports content → the reclassification pass "
        "completes without the per-row file-check overhead; sport and league "
        "tags come out unchanged.",
        "Edit the sports definitions in Settings while the app runs → the "
        "next classification pass picks the change up within a second.",
    ),
)

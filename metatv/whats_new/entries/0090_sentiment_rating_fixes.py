from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=90,
    version="0.9.0",
    date="2026-06-28",
    title="Details pane: 'Not Interested' is exclusive; unrated titles hide the rating",
    items=(
        "The 👍 / 🙅 / 👎 sentiment buttons are now one mutually-exclusive group: "
        "marking 'Not Interested' clears any like/dislike, and liking/disliking "
        "clears 'Not Interested' (previously only like and dislike cleared each other).",
        "Titles with no rating (a 0 / '0.0' rating from the provider) no longer show "
        "'★ 0.0 of 10' — the rating is simply hidden.",
    ),
    test_steps=(
        "On a VOD title, click 👍 (like), then click 🙅 (Not Interested): the like must "
        "clear and only Not Interested stays active.",
        "Then click 👎 (dislike): Not Interested must clear and only dislike stays active.",
        "Open a title the provider gives no rating for (or a 0 rating) and confirm the "
        "star rating line is hidden — not shown as '0.0 of 10'.",
    ),
    # These fixes (shipped in PR #248) resolve the two failures logged against
    # entry 78 (PR #235) in the dev QA checklist — declaring them here marks
    # those steps Addressed so the tester only needs to re-test and pass.
    addresses=("e78_s3", "e78_s5"),
)

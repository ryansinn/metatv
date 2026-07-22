from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=144,
    version="0.9.0",
    date="2026-07-22",
    title="Global Exclusions no longer hide content in a language you didn't exclude",
    items=(
        "The Global Exclusions dialog hides prefix codes (grouped under language "
        "headings). Until now an excluded code also matched a channel's region tag, "
        "so an English movie filed under, say, an \"India Hindi Subs\" category was "
        "dropped when you excluded India — even though you never excluded English.",
        "Language now wins over region: a channel with an explicit prefix you did "
        "NOT exclude (e.g. EN) is always shown, regardless of its region tag. The "
        "region only decides visibility when the channel has no prefix to speak for "
        "it. This can only reveal content, never hide more.",
        "Result: searches and alerts stop silently swallowing English (or any "
        "un-excluded-language) results that happened to be filed under an excluded "
        "region.",
    ),
    test_steps=(
        "Exclude a region-ish code (e.g. India / IN) in Global Exclusions, then search "
        "for a title that has an English (|EN|) version filed under that region: the "
        "English result is now shown, not hidden.",
        "Confirm content whose PREFIX you actually excluded (e.g. Arabic / AR) is still "
        "hidden, and the gold bar's \"hidden by Global Exclusions\" count reflects only "
        "the genuinely-excluded (prefix-matched or prefix-less region-matched) items.",
        "Search a title with a prefix-less entry filed under the excluded region and "
        "confirm it is still hidden (region fallback applies when there is no prefix).",
    ),
)

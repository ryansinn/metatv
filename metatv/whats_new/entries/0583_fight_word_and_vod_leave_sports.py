from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=583,
    version="0.94.0",
    date="2026-09-03",
    title="Sports no longer guesses from the word 'fight' or claims movies",
    items=(
        "The word 'fight' in a title no longer classifies anything as "
        "sports — it was pulling Netflix films and cartoons into the sports "
        "population (measured: 4,611 movies and 421 series filed under "
        "Sports, many gated in only by 'Fight' in the title).",
        "Movies and series can no longer enter the sports population at "
        "all — a title available on demand is not 'on now'; live channels "
        "are unaffected.",
        "A one-time repair pass at next launch removes roughly 5,000 "
        "wrongly-filed rows.",
    ),
    test_steps=(
        "After the launch repair, search 'The Big Fight' → the title shows "
        "as a movie/series with no sports filing.",
        "Live channels like 'UFC FIGHT PASS' remain classified as sports.",
    ),
)

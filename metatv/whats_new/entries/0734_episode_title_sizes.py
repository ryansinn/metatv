from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=734,
    version="0.171.0",
    date="2026-10-19",
    title="Details: show and episode titles one size smaller in episode view",
    items=("With an episode selected, the show's name and the episode's title are each one "
           "size smaller, so long episode titles stop wrapping onto a second line as often. "
           "Movies, series and live channels keep the big title.",),
    test_steps=("Select an episode with a long title (e.g. It's Always Sunny S18E09) — the show "
                "name and the episode title are both smaller than before and the episode title "
                "fits on fewer lines; select the series itself — its title is full size again.",),
)

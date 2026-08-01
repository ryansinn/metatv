from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=193,
    version="0.15.0",
    date="2026-07-31",
    title="Recommendations: a healthier movie/series mix",
    items=(
        "The Recommended sidebar (and the Recommendations dashboard) no longer fills "
        "up with only movies. Scoring was volume-biased — titles with richer metadata "
        "(more cast, longer plots) out-scored thinner ones just for having more to "
        "match on, and there are simply more movies than series. Each attribute now "
        "scores by the average strength of its matches instead of a raw sum, so a big "
        "cast or a keyword-dense plot can't inflate a title's score.",
        "A performer now has to show up across at least two of your liked/favorited "
        "titles before it counts toward recommendations — and even then only lightly — "
        "so no single actor or director takes over your suggestions.",
        "Within a single set of recommendations, once a title with a given liked "
        "performer is shown, the next candidate sharing that performer is knocked down "
        "so other content gets room to surface. Queue, like, or dismiss the shown one "
        "and the next refresh can rotate in other titles with that performer.",
        "The Recommended list now interleaves movies and series so both are represented "
        "(led by whichever has the stronger match), instead of one type crowding out the "
        "other.",
    ),
    test_steps=(
        "Rate/like or favorite a few movies AND a few series, then open the sidebar "
        "Recommended section: the list should contain BOTH movies and series (not all "
        "one type), each still shown with its media-type icon.",
        "With several liked titles sharing one actor, open Recommended: you should NOT "
        "see the same actor's films stacked back-to-back filling the list — other "
        "content is interleaved between them.",
        "Open the Recommendations dashboard (Preferences view): recommendations there "
        "should likewise show a mix of movies and series, ranked by preference match.",
    ),
)

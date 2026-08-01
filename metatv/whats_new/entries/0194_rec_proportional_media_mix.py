from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=194,
    version="0.15.0",
    date="2026-08-01",
    title="Recommendations follow your own movie/series balance",
    items=(
        "The Recommended list no longer forces a flat half-movies/half-series split. It "
        "now follows the balance of what you actually engage with — likes, favorites, "
        "queue and plays — so a mostly-movies library gets mostly movies.",
        "The share is square-root damped so the smaller type never disappears: 100 "
        "movies to 15 series lands at roughly 72 : 28 (7 movies and 3 series in a "
        "10-item list), not 87 : 13. An even history stays even, an all-one-type "
        "history stays all-one-type, and a brand-new library starts at 50 : 50.",
        "The Recommendations dashboard shows the ratio in use next to a Mix slider — "
        "drag it to set your own split, or press Automatic to hand the decision back. "
        "The sidebar Recommended section follows the same setting.",
    ),
    test_steps=(
        "Open the Recommendations dashboard: next to 'Recommended for you' the Mix "
        "label reads 'Automatic (NN : NN)' and the slider sits on that computed share.",
        "Drag the Mix slider well toward movies (e.g. 90) and wait a moment: the label "
        "switches to the plain ratio, the list re-scores, and movies clearly dominate it.",
        "Press Automatic: the label goes back to 'Automatic (NN : NN)', the button "
        "greys out, and the list returns to the computed mix.",
        "Restart MetaTV with a manual mix set: the slider and label come back with your "
        "override still applied (not reset to Automatic).",
        "Open the sidebar Recommended section: its movie/series balance matches the "
        "dashboard's ratio rather than a rigid alternation.",
    ),
)

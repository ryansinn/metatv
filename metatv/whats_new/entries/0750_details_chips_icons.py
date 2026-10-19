from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=750,
    version="0.187.0",
    date="2026-10-19",
    title="Details pane, filter chips, Recipe bar and tag cloud use the same clean icons",
    items=("Filter dropdowns show a caret icon after their label, and the Exclusions and "
           "watch-rule chips show a state dot after theirs. Liked and disliked actors in "
           "the details pane carry trend icons, the poster's watched badge is a check "
           "icon, measured quality badges carry a verified icon, and the preferred "
           "version line shows a target. The Recipe bar's ingredient chips end in a close "
           "icon and say 'not …' for an excluded ingredient. The tag cloud marks included "
           "and excluded tags with icons.",),
    test_steps=("Open the EPG On Now view — the Category and All Types dropdowns show a "
                "caret icon after the words.",
                "Open a movie whose cast includes an actor you've liked — that actor's chip "
                "carries an upward trend icon.",
                "Add an excluded tag to a Recipe — its chip reads 'not <tag>' and ends with "
                "a close icon; clicking it removes the ingredient."),
)

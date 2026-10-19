from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=735,
    version="0.172.0",
    date="2026-10-19",
    title="Details: \"Series overview\" when an episode has none of its own",
    items=("Most sources send no description for individual episodes, so the details pane "
           "keeps the show's description. It is now headed \"Series overview\" instead of "
           "\"Overview\", so it isn't mistaken for the episode's, and whether you keep it "
           "collapsed is remembered separately from a real overview.",),
    test_steps=("Select an episode whose source has no episode description — the section reads "
                "\"Series overview\"; collapse it, select a movie — its \"Overview\" is still open; "
                "back to the episode — \"Series overview\" is still collapsed.",),
)

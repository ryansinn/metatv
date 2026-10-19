from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=733,
    version="0.170.0",
    date="2026-10-19",
    title="Details: rating beside the title, collections with the genres, episode first",
    items=("The rating and its TMDb/IMDb chips sit at the right end of the title's line; the "
           "genres get a row of their own underneath, and the collection a title is filed "
           "under (e.g. \"Top Series\") ends that row in its own colour.",
           "Selecting an episode puts its title and \"SEASON · EPISODE\" line directly under "
           "the show's name, above the show's genres. The episode title is now the large "
           "one, the show's name steps down a size, and only the episode's rating shows.",
           "The empty space that could open between the genres and \"Available in\" is gone."),
    test_steps=("Select a series with several genres — its rating is at the right of the title "
                "line, the genres (then the collection chip, in a different colour) follow on "
                "their own row, and \"Available in\" starts right below with no empty gap.",
                "Select one of its episodes — under the show's (now smaller) name comes the large "
                "episode title with its rating at the right, then the SEASON · EPISODE line, then "
                "the show's genres; the show's own rating is gone."),
)

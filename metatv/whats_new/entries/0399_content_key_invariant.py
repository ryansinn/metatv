from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=399,
    version="0.52.0",
    date="2026-08-27",
    title="Quitting mid-setup could split a film away from its own copies",
    items=(
        "Two of the one-time setup passes had to run in order: one reads each "
        "title's matching id from your source, and a later one uses that id to "
        "decide which copies are the same film. They are tracked separately, "
        "and only the second one remembers it finished.",
        "So if you quit the app while the first pass was still running, it "
        "resumed on the next launch while the second one considered itself "
        "done and sat out. Every title it filled in on that second attempt got "
        "an id that nothing then used.",
        "Those titles stopped matching their own other copies. A film with an "
        "English and a Spanish version could show up as two separate entries, "
        "and because recommendations weigh what you like by title, one film "
        "you rated could be counted twice.",
        "The first pass now records both things at once, so it no longer "
        "depends on the second one running afterwards. Nothing was wrong in "
        "libraries where setup ran start to finish, and no ratings, favourites "
        "or tags were ever touched.",
    ),
    test_steps=(
        "Open a film you own in more than one language or quality. The details "
        "pane's 'Other Versions' should list the other copies, not be empty.",
        "Turn on Settings - Interface - Channel List - collapse variants, then "
        "search that film's title. It should collapse to a single row rather "
        "than one row per language.",
        "Like a film that has several copies, then open Recommendations and "
        "confirm its genre is not weighted more heavily than a film you liked "
        "that only exists once.",
        "Confirm your existing likes, favourites and tags are all still there "
        "after this update.",
    ),
)

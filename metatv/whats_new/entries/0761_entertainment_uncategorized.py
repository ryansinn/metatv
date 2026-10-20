from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=761,
    version="0.198.0",
    date="2026-10-20",
    title="\"TV Show\" retired; new Entertainment genre; Uncategorized row",
    items=("\"TV Show\" is no longer a genre: providers used it for \"programme\" and "
           "\"series\", which says nothing about the genre. Those titles now sit in the "
           "Genre filter's Uncategorized row, which you can show or hide like any other.",
           "Entertainment is a new genre for what broadcasters label light entertainment — "
           "reality competitions, game shows, variety.",
           "Swedish pop-culture and celebrity shows now count as Talk Show."),
    test_steps=("Launch, let the tidying finish, open the Genre filter — no \"TV Show\" row; "
                "an \"Uncategorized\" row sits at the bottom with a count, and Entertainment "
                "is listed.",
                "Untick Uncategorized — titles with no genre leave the list; tick it again "
                "and they return."),
)

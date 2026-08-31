from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=470,
    version="0.60.0",
    date="2026-08-31",
    title="Sports is ordered by when things are on",
    items=(
        "Filtering Sports to a single sport showed fixtures from days ago at "
        "the top and nothing from today. The list was sorted alphabetically, "
        "so \"US Open: Court 5…\" simply came early — a finished match always "
        "outranked one about to start.",
        "Sports is now ordered by time, in four groups: on now, upcoming "
        "(soonest first), 24/7 channels, and finished (most recent first, "
        "always last). Of 309 US Open rows in a typical library, 219 were "
        "finished — those now sit at the bottom instead of filling the screen.",
        "Two more ways providers write a date are now read: a time in "
        "brackets at the end of the name, and the \"@ Aug 27 11:00 AM\" form "
        "the tennis listings use. Together with yesterday's three, MetaTV now "
        "dates 4,205 fixtures where it managed 1,527.",
        "Countdowns tick by the minute instead of the second, and an event "
        "already under way says how long it has been on rather than counting "
        "down past zero. There is a new Live timing setting if you want only "
        "countdowns, or nothing at all.",
        "Your library is updated in place on the next launch; you do not need "
        "to refresh your sources.",
    ),
    test_steps=(
        ("Open Sports and filter to Tennis. The top of the list should be "
         "today's fixtures, not last week's.", "view:sports"),
        "Scroll to the bottom of that filtered list and confirm finished "
        "fixtures are grouped there rather than mixed in.",
        "Confirm a 24/7 channel such as a tennis network still appears — it "
        "has no start time, so it sits between upcoming and finished.",
        ("Open Events and watch a countdown for a minute; it should change "
         "once, not sixty times.", "view:events"),
        "Find an event that has already started and confirm it reads how long "
        "it has been on, not a negative countdown.",
    ),
)

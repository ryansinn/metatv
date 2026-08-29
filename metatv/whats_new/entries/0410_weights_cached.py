from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=410,
    version="0.53.0",
    date="2026-08-28",
    title="Recommendations are worked out once, not once per panel",
    items=(
        "Working out what you like reads every stored plot in your library and "
        "weighs the words in them. On a large library that takes about four "
        "seconds.",
        "Six parts of the app asked for that separately - the sidebar, Discover, "
        "the details pane, Explore, the preferences screen and search. A single "
        "startup could run the whole calculation six times in thirty seconds, "
        "on identical information.",
        "That is around twenty seconds of work for one answer, and on a slower "
        "machine those runs overlap - which is one way 'Couldn't load "
        "recommendations' happens.",
        "The result is now shared. It is recalculated when your taste actually "
        "changes - the moment you like, dislike or watch something - so nothing "
        "is ever stale, and it is refreshed periodically as new title details "
        "arrive in the background.",
    ),
    test_steps=(
        "Start the app and open Recommendations. It should appear without a "
        "long pause.",
        "Open Discover and the details pane for a title - neither should stall "
        "while recommendations recalculate.",
        "Like or dislike something, then reopen Recommendations and confirm the "
        "suggestions reflect it.",
        "Check the log during startup - 'IDF corpus' should appear once, not "
        "repeatedly.",
    ),
)

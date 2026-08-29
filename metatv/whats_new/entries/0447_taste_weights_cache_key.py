from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=447,
    version="0.56.0",
    date="2026-08-29",
    title="Playing something no longer freezes the next click",
    items=(
        "Play a movie, then click any other title, and the app locked up for "
        "about two seconds before the details filled in. Every time.",
        "The app works out your taste - which genres, directors and actors you "
        "lean toward - by reading every plot in your library and weighing the "
        "words. That is 121,667 plots, and it takes about two seconds.",
        "It is meant to be worked out once and remembered until your taste "
        "actually changes. It was instead being thrown away every time you "
        "played anything, because playing updates a 'last played' date the "
        "calculation was watching - and never actually reads.",
        "So the answer was recalculated, on the same thread that draws the "
        "window, to arrive at exactly the number it had just discarded.",
        "The opposite bug sat next to it: favouriting something DOES change "
        "your taste, and was not being watched at all, so a new favourite took "
        "up to ten minutes to count.",
        "Both now watch the right things. Selecting a title after playing one "
        "went from 2,118ms to 0.1ms.",
    ),
    test_steps=(
        "Play a movie, close the player, then click through several other "
        "titles and confirm the details pane fills in immediately with no "
        "pause.",
        "Favourite a movie you have not rated, then open Recommendations and "
        "confirm it reflects the new favourite rather than taking minutes.",
        "Rate a movie up or down and confirm recommendations shift right away.",
    ),
)

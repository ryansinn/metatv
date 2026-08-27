from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=396,
    version="0.51.0",
    date="2026-08-27",
    title="'Make recipe' in Explore now arrives with an ingredient",
    items=(
        "Clicking 'Make recipe' on a title in the Explore trail map took you "
        "to the Recipe builder and left it empty, which looked like the button "
        "doing nothing. It now seeds the recipe with that title's genre, so "
        "you land on results rather than a blank page.",
        "Only the genre is seeded, deliberately. Seeding every facet a title "
        "has - genre and language and decade and region - narrows the recipe "
        "so far it usually returns just the title you started from. The rest "
        "are one click away in the builder you have landed in.",
    ),
    test_steps=(
        "Open a title's details, open Explore, and click 'Make recipe' on a "
        "title that has a genre - the Recipe view should open with that genre "
        "already an ingredient and results showing.",
        "Confirm the genre shown as the ingredient matches the title you "
        "clicked from.",
        "Add a second ingredient in the builder and confirm results narrow as "
        "normal - the seeded recipe must behave like a hand-built one.",
        "Find a title with no genre (a live channel, or an unparsed movie) and "
        "click 'Make recipe' - it should still open the builder, empty, rather "
        "than doing nothing at all.",
        "Compare with the details-pane route: right-click a genre tag and "
        "choose the Recipe action - both should land you in the same place.",
    ),
)

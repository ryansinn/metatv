from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=527,
    version="0.71.0",
    date="2026-09-02",
    title="Search headings look like the rest of the app, and fold",
    items=(
        "The Titles and Cast & Crew headings were drawn their own way — a "
        "caret, sentence case, and the count in brackets at the same weight "
        "as the label. They now follow the same heading style the sidebar "
        "uses everywhere else: a quiet small-caps label with the count "
        "brighter and larger beside it, and no caret. Clicking the heading "
        "still collapses it; that has always been what the heading is for.",
        "A person's name under Cast & Crew was too faint to lead the films "
        "beneath it. It now takes the bright text and carries a count of how "
        "many titles they are in.",
        "Each person can be folded away on their own, so a search that "
        "surfaces one actor across forty titles can be pushed aside without "
        "collapsing the whole section. The name and its count stay behind.",
    ),
    test_steps=(
        ("Search anything and look at the Titles / Cast & Crew headings — "
         "small caps, no caret, and the number brighter and larger than the "
         "word beside it.", "view:list"),
        ("Click a heading. It should still collapse and expand, and the count "
         "must remain readable while collapsed.", "view:list"),
        ("Search an actor's surname and click one person's name. Only their "
         "films fold away; the name and its count stay, and everyone else is "
         "untouched.", "view:list"),
        ("Click the same name again and confirm their films come back in the "
         "same order.", "view:list"),
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=526,
    version="0.71.0",
    date="2026-09-02",
    title="Cast & Crew names render as headings, not as blank rows",
    items=(
        "The person's name under Cast & Crew was drawn as if it were a "
        "result: full row height, with the space where a poster and the "
        "title, year and quality would go left empty.",
        "It now draws as the label it is — one line, in the same quiet style "
        "throughout, with nothing on it to click.",
    ),
    test_steps=(
        ("Search an actor's surname. Each person's name under Cast & Crew "
         "should be a single compact line, noticeably shorter than the "
         "result rows beneath it.", "view:list"),
        ("Confirm there is no empty poster space or blank columns on the "
         "name row, and that hovering it offers no star or rating controls.",
         "view:list"),
    ),
)

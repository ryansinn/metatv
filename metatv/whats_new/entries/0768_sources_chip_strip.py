from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=768,
    version="0.205.0",
    date="2026-10-31",
    title="Sources: a strip of source chips, and the editor gets the full width",
    items=("The Sources page's left column of sources is gone. Your sources are now chips "
           "across the top — icon, status dot and name, with \"expired\", \"disabled\" or the "
           "days left in smaller text underneath — and the editor below uses the whole width.",
           "Hover a chip for the full name; with many sources the chips wrap onto a second row.",),
    test_steps=("Open Sources — your sources are chips in the header beside Add Source, and the "
                "editor starts at the left edge of the page.",
                "A long name shows its first 14 characters and \"…\"; hovering shows the full name, "
                "its state and the days left.",
                "An expired source's chip has a red dot and says \"expired\" underneath; a disabled "
                "one has a grey hollow dot and says \"disabled\"; an active one says how many days "
                "are left.",
                "Click another chip — it is highlighted and the editor switches to that source.",),
)

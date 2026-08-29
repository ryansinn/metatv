from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=442,
    version="0.55.0",
    date="2026-08-29",
    title="A source's addresses are tinted by how well they actually work",
    items=(
        "The URL list already showed a reliability percentage per address. It "
        "now carries a very light background tint to match, so the healthy and "
        "the struggling addresses separate at a glance.",
        "The tint follows the same score the list is sorted by, so the colours "
        "and the order always agree.",
        "A recent failure shows immediately, and an old one fades as the "
        "address keeps working - a single blip weeks ago does not brand an "
        "address forever.",
        "An address nobody has tested yet gets no tint at all. It reads as "
        "'Untested', which is the truth, rather than being coloured as though "
        "it were known to be good.",
        "The percentage stays on the row - the colour is a second reading of "
        "it, never the only one.",
    ),
    test_steps=(
        "Open a source with several URLs and confirm working addresses carry a "
        "faint green tint and failing ones a faint red.",
        "Add a brand-new URL and confirm it shows 'Untested' with no tint.",
        "Confirm the tint order matches the list order - no green address "
        "sitting below a red one.",
        "Switch themes and confirm the tints remain subtle and readable in "
        "each.",
    ),
)

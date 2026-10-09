from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=688,
    version="0.133.0",
    date="2026-10-09",
    title="A calmer Details section",
    items=(
        "Details is one plain row per fact under a thin left rule: the value, "
        "then where it came from. No more group headings or boxed chips.",
    ),
    test_steps=(
        "Open 'Details for …' — each row reads 'Language  English · TREX Shared'; "
        "the block hangs from a thin rule on its left, clearly apart from the title.",
        "A guessed fact is italic with '· guessed from …' after it.",
        "Click a value — the list filters to it; right-click — Discover opens.",
    ),
)

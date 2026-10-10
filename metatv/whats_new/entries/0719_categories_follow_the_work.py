from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=719,
    version="0.158.0",
    date="2026-10-10",
    title="Your categories follow the title to every active source",
    items=("A title you filed under one of your categories now shows on that shelf "
           "from any active source that carries it — once per title — even when the "
           "copy you filed is on a disabled source.",
           "A facet's tag cloud shows each count small at the name's top right.",
           "The Video row no longer shows a bitrate."),
    test_steps=("File a movie under a category, then disable that copy's source — the "
                "category shelf in Discover still shows the title from another source "
                "that has it.",
                "Open Recipe → Cast — counts sit small beside each name, not at its size."),
)

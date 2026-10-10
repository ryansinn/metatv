from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=718,
    version="0.157.0",
    date="2026-10-10",
    title="Details says plainly where each fact came from",
    items=("'Get stream details' moved into the Details heading, left of the count.",
           "Captions read 'reported by source', 'guessed from title', and a decade taken "
           "from a year in the name says 'deduced from title'.",
           "Language and Original language rows that only repeat the one audio track "
           "are gone.",
           "The ✓ on a copy's quality and the 'Re-check stream' label now appear only "
           "after the stream was actually played or probed — not for the source's own "
           "report."),
    test_steps=("Open a movie whose stream was never played — the heading shows "
                "'Get stream details', the quality chip has no ✓, the decade says "
                "'deduced from title'.",
                "Press 'Get stream details' — the chip gains ✓ and the button reads "
                "'Re-check stream'."),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=779,
    version="0.215.0",
    date="2026-11-01",
    title="A source's guide goes to its own channels, never to an expired source",
    items=("When two sources carry a channel with the same guide id, the guide from a source's "
           "feed now attaches to that source's own channel, and never to a disabled or expired "
           "source. On TREX, 46 more of its own channels get their guide, and the 60 links that "
           "had gone to an expired source are gone.",),
    test_steps=("Refresh TREX's guide (or open the EPG view, which re-links) — then open "
                "Sources → TREX → Analytics: the guide tile's tooltip counts more TREX channels "
                "with guide data than before.",
                "A channel from an expired source shows no guide data.",),
)

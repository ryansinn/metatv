from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=778,
    version="0.214.0",
    date="2026-11-01",
    title="Quitting no longer risks a crash on the way out; TK is Tajikistan",
    items=("MetaTV now closes its main window itself before exiting, instead of leaving it to "
           "the toolkit's exit-time cleanup, which could crash after everything had saved.",
           "Channels filed under TK (Dushanbe HD, TV Sugd…) count as Tajikistan.",),
    test_steps=("Quit MetaTV (Cmd/Ctrl+Q) a few times — it exits without a crash report.",
                "Sources → TREX → Analytics → Unrecognized prefixes — TK is no longer listed.",),
)

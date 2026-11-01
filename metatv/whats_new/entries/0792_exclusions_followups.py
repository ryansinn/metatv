from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=792,
    version="0.228.0",
    date="2026-11-01",
    title="Exclusions: Adult moves to Platforms, dialog opens larger",
    items=("Adult is no longer listed under Languages — it sits with Kids, Sports, Music and the other "
           "content groups under Platforms.",
           "The Exclusions dialog opens large enough for the category and genre grids, and reopens at "
           "the size you last left it.",
           "Note from the previous update: the old Content Types filter was inverted and kept only "
           "Kids/Religious-labelled live channels, hiding about 30,000 others (ESPN among them) from the "
           "channel list. Those channels are visible again.",),
    test_steps=("Open Exclusions, expand Languages — no Adult group; expand Platforms — Adult is there.",
                "Resize the dialog, press Cancel, reopen it — same size.",),
)

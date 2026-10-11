from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=722,
    version="0.161.0",
    date="2026-10-10",
    title="Pay-per-view is a content type; excluding a country covers all its codes",
    items=("Channels in groups labelled PPV or 'Pay per view' are tagged PPV, which you "
           "can exclude in Global Exclusions → Content Provenance; 'Ppv' no longer "
           "clutters collection names.",
           "Excluding a country now hides it under every code it goes by — DK also "
           "hides DNK and DEN, SE also SW and SWE.",
           "A one-time pass re-tags the PPV channels."),
    test_steps=("Restart and let the tag update finish.",
                "Global Exclusions shows PPV under Content Provenance; tick it — PPV "
                "groups disappear from the channel list and Recipe.",
                "With Denmark (DK) excluded, the 'DENMARK … PPV' groups are hidden."),
)

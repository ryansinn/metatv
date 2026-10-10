from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=721,
    version="0.160.0",
    date="2026-10-10",
    title="Channel groups named after a country now carry that country",
    items=("A provider group like 'SWEDEN SOCCER PPV' or 'NORWAY TV2 PLAY PPV VIP' now "
           "gives its channels the region Sweden / Norway (and the language guess), so "
           "your Global Exclusions apply to them.",
           "Kuwait, Qatar, the Baltic states and other countries that showed as bare "
           "codes now have names.",
           "A one-time pass updates the affected channels."),
    test_steps=("Restart and let the tag update finish.",
                "With Sweden excluded, browse live channels — the 'SWEDEN … PPV' groups no "
                "longer appear; in Recipe, 'Norway Tv2 Play Ppv Vip' no longer leads the "
                "collection cloud."),
)

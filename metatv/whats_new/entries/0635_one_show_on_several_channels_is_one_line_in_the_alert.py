from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=635,
    version="0.103.0",
    date="2026-09-08",
    title="One show on several channels is one line in the alert",
    items=(
        "A watch alert that caught several channels carrying the same "
        "programme listed each one: \"14 shows starting in 14 min — Two and a "
        "Half Men, Two and a Half Men, Two and a Half Men and 11 more\". The "
        "banner now counts distinct titles and names three different ones, so "
        "the other shows starting at the same time are visible.",
        "When every match is one show on several channels, the alert says so: "
        "\"On BBC One and 2 other channels\".",
    ),
    test_steps=(
        "Watch a title that several channels carry, and let its start time come "
        "inside the alert window → one banner naming that show once, with the "
        "channel count.",
        "With several different shows starting together → the banner counts "
        "distinct titles and names three different ones.",
    ),
)

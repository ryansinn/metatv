from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=489,
    version="0.64.0",
    date="2026-09-01",
    title="Watching something did not always count",
    items=(
        "If the pre-flight check failed and you chose Play Anyway, the stream "
        "played but nothing recorded it — no History entry, no play count, and "
        "no resume position.",
        "The same was true of the 'Try <source>' actions offered when a stream "
        "fails, and of playing an episode.",
        "Only the fully-validated path recorded a play. Every play you choose "
        "now counts, whichever way you started it.",
    ),
    test_steps=(
        ("Play something whose check fails, choose Play Anyway, and confirm it "
         "appears in History straight away.", "view:list"),
        ("Play an episode and confirm History records it.", "view:history"),
        "When a stream fails and offers another source, use it and confirm "
        "that play is recorded too.",
    ),
)

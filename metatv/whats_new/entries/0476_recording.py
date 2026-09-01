from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=476,
    version="0.64.0",
    date="2026-08-31",
    title="Record what's on",
    items=(
        "Right-click a live channel and choose Record what's on. It records "
        "the programme the guide says is airing, starting two minutes early "
        "and running fifteen minutes over, because sport overruns.",
        "A recording takes the source's connection — but never by surprise. "
        "If nothing is playing it just starts. If you are watching, you get a "
        "countdown at ten minutes, five, one, and thirty seconds, and every "
        "one of those is a chance to cancel the recording and keep watching.",
        "You can push a running recording's finish time out while it is still "
        "going, which is the thing that saves an event that ran long. The stop "
        "time is worked out as it goes rather than fixed when you scheduled it.",
        "Padding works both ways: start twenty minutes late to skip a pregame "
        "show, as easily as finishing twenty minutes late.",
        "If another recording already wants that source at the same time, you "
        "are told when you schedule it — while you can still choose — not at "
        "the moment one of them silently fails to start.",
        "Recordings are saved to their own Recordings folder, beside Downloads "
        "rather than mixed in with it.",
    ),
    test_steps=(
        ("Right-click a live channel with guide data and choose Record what's "
         "on; the notice should name the finish time, fifteen minutes after "
         "the programme ends.", "view:epg"),
        "Right-click a movie and confirm Record is not offered — only Download.",
        "Start watching that source, then schedule a recording due in a few "
        "minutes. You should get a countdown warning, and cancelling the "
        "recording should leave your stream alone.",
        "Schedule a recording while nothing is playing and confirm you get no "
        "countdown warnings at all.",
        "Schedule two recordings that overlap on the same source and confirm "
        "the second one warns you about the clash as you add it.",
        "Let a short programme record and confirm the file lands in the "
        "Recordings folder, not beside your downloads.",
        "Choose Record what's on twice for the same programme and confirm the "
        "second is refused rather than recording it twice.",
    ),
)

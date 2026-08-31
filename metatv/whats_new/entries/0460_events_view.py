from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=460,
    version="0.59.0",
    date="2026-08-30",
    title="An Events view, with the countdown on every card",
    items=(
        "New Events chip in the switcher. It shows your dated content — "
        "pay-per-view and live events — as cards, soonest first, each with a "
        "countdown that ticks: \"in 3d 4h\", \"in 12m 30s\", \"ended 2d ago\".",
        "One view with a scope switch rather than two: All, Pay-per-view, Live "
        "events. The rows are the same shape and the difference is which "
        "bucket the provider filed it under.",
        "Order is upcoming first, then what has ended, then the always-on "
        "feeds — 923 of your live-event entries have no start time at all "
        "because they simply run continuously, and burying those under 900 "
        "finished fights would be the wrong answer to \"what can I watch\".",
        "Channels from a source you have switched off never appear, in this "
        "view or in Sports.",
        "This replaces an old PPV screen that was never reachable from "
        "anywhere in the app.",
    ),
    test_steps=(
        ("Click the Events chip. Cards should appear with a title, a date, a "
         "countdown and a Play button.", "view:browse"),
        "Check the order: things happening soon are first, finished events "
        "come after them, and always-on feeds are last.",
        "Watch a card whose event is under a day away — its countdown should "
        "tick every second. One that is days away should show \"in 3d 4h\" and "
        "not flicker.",
        "Switch to Pay-per-view, then Live events. The count beside the "
        "filters should match what is shown, and the badges should differ — "
        "PPV cards show quality and sport, live events show the network.",
        "Click Play on a card and confirm it plays.",
        "Switch to another view and back; nothing from the previous scope "
        "should linger.",
        "Turn a source off in Sources and confirm its events disappear.",
    ),
)

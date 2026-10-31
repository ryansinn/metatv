from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=765,
    version="0.202.0",
    date="2026-10-31",
    title="Shortened sidebar titles show in full on hover",
    items=("When a title is too long for the sidebar and shows with \"…\", hovering it now "
           "shows the full title on the first line of the tooltip, above the usual details "
           "(why it was recommended, when it airs). Works in every sidebar list: "
           "Recommended, History, Favorites, Watch Queue, Watch Alerts and transfers.",
           "Download and recording rows now show their progress tooltip, which never "
           "appeared before.",),
    test_steps=("Narrow the sidebar until a Recommended title shows \"…\", hover it — the "
                "tooltip's first line is the full title, then the reason and genres.",
                "Hover a title that fits — the tooltip is unchanged, with no repeated title.",
                "Do the same in Watch Alerts, History and Watch Queue — a shortened title "
                "shows in full on hover.",
                "Start a download and hover its row in the sidebar — its progress tooltip "
                "appears.",),
)

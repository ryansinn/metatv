from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=776,
    version="0.212.0",
    date="2026-10-31",
    title="Source Analytics, re-laid out: tiles, two columns, nothing cut off",
    items=("The Analytics tab in the Sources editor uses the width: the headline numbers are tiles "
           "across the top (titles only on this source, films, series, live, guide coverage, days "
           "left, plays started, connection limit), and the cards sit in two columns — what the "
           "source carries on the left, how it behaves on the right. It takes half the height.",
           "Every list longer than it shows has Show all, which opens it in place: all regions, "
           "all server addresses, every unrecognized prefix. Bars are short instead of stretched "
           "across the page.",
           "Click a region in Titles by region to browse that region's titles on the source.",
           "What you watch here says how many of the titles you've played are on no other source, "
           "what you played in the last 30 days, episodes and series, favourites, and a Most "
           "played list with type, plays and when.",),
    test_steps=("Open Sources → TREX → Analytics in a wide window — tiles across the top, then "
                "What you watch / Shared on the left and Playback / Connections / Server addresses "
                "on the right.",
                "Click Show all (209) under Titles by region — every region appears in place; "
                "Show fewer folds them back. Same under Server addresses and Unrecognized prefixes.",
                "Click \"India (IN)\" — Search opens on India's titles from that source.",
                "Narrow the editor below ~860 px — the cards stack in one column and regions show "
                "two across.",
                "What you watch here shows \"N of the M titles you've played are on no other "
                "source\" and a Most played list.",),
)

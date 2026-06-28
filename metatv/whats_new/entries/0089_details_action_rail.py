from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=89,
    version="0.9.0",
    date="2026-06-28",
    title="Details pane: all actions moved into a vertical icon rail",
    items=(
        "Every action button (Favorite, Play, Add to Queue, Like / Not Interested / "
        "Dislike, Alert, Watchlist, Hide) now lives in a slim icon-only rail to the "
        "left of the poster instead of in rows beneath it — reclaiming vertical space "
        "so less scrolling is needed to read a title's details.",
        "The rail now appears for live channels too (next to the channel header), so "
        "the action icons are always present regardless of channel type.",
        "Buttons are icon-only with hover tooltips; current state shows as a "
        "highlighted (checked) button or a swapped icon (e.g. filled vs. outline star).",
    ),
    test_steps=(
        "Open a movie/series in the details pane. Confirm Favorite (top), then Play, "
        "Add to Queue, the 👍/🙅/👎 trio, and Hide (bottom) appear as a vertical icon "
        "rail left of the poster — and there are no action button rows under the poster.",
        "Hover each rail icon and confirm a tooltip describes it (e.g. 'Play this "
        "channel', 'Add to Watch Queue').",
        "Click Favorite and Add to Queue; confirm the star fills / the queue button "
        "highlights and the change persists (re-open the title).",
        "Open a SERIES and confirm an Alert (🔔) button appears in the rail; toggle it "
        "and confirm it highlights.",
        "Open a LIVE channel and confirm the action rail is still visible to the left "
        "of the channel header (Favorite, Play, Add to Queue, Watchlist, Hide).",
    ),
)

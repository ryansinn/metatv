from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=99,
    version="0.9.0",
    date="2026-06-28",
    title="Details pane: actions tiered by how often you use them",
    items=(
        "Play and Resume are now full-size, labeled buttons in a row directly below "
        "the poster (the most-used actions get the prominent slot). Play always "
        "starts from the beginning; Resume continues from where you left off and "
        "shows the saved position (e.g. 'Resume 5:00').",
        "For a partially-watched movie, Play and Resume sit side-by-side and split "
        "the width 50/50 — Resume is the dominant filled-orange button. With no saved "
        "position, a single full-width Play is shown. Live channels show a full-width "
        "Play only.",
        "The watched state moved onto the poster as a clickable check badge "
        "(Plex/Jellyfin style): a solid badge when watched (click to mark unwatched) "
        "and a faint badge that appears on hover when unwatched (click to mark "
        "watched). Live channels have no badge.",
        "The slim icon rail left of the poster now holds only the infrequent actions: "
        "Favorite, Add to Queue, the 👍/🙅/👎 trio, Alert, Watchlist, and Hide.",
        "Double-clicking a title resumes when there's a saved position and starts "
        "from the beginning otherwise — matching the dominant Resume button.",
    ),
    test_steps=(
        "Open a movie with NO saved position. Confirm a single FULL-WIDTH 'Play' "
        "button appears directly below the poster (no Resume), and the rail no longer "
        "contains Play/Resume.",
        "Open a PARTIALLY-WATCHED movie. Confirm 'Play' and 'Resume M:SS' appear "
        "side-by-side splitting the width 50/50, with Resume the filled-orange "
        "(dominant) button showing the saved position; click Resume and confirm "
        "playback continues from that position.",
        "Click the secondary 'Play' button on the same title and confirm it starts "
        "from the beginning (position 0).",
        "Open a LIVE channel. Confirm a single full-width 'Play' shows below the "
        "logo/header, there is NO Resume, and NO watched badge on the poster.",
        "On a WATCHED movie poster, confirm a solid check badge shows in the corner; "
        "click it and confirm the title becomes unwatched (badge turns faint).",
        "On an UNWATCHED movie poster, confirm no badge until you hover the poster; "
        "hover to reveal the faint check, click it, and confirm the title is marked "
        "watched (badge becomes solid).",
        "Double-click a partially-watched movie in the channel list and confirm it "
        "RESUMES from the saved position (not from the beginning).",
    ),
)

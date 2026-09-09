from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=648,
    version="0.111.0",
    date="2026-09-08",
    title="Reactivating a dead source and playing it now reaches History",
    items=(
        "\"Reactivate & play\" (the failure toast's action for a channel whose only "
        "working copy sits on a disabled source) played fine but never counted: it "
        "never bumped play count, never appeared in History, and never registered "
        "for resume/watch-progress capture. The function's signature did not even "
        "carry a channel id, so it could not have recorded anything. It now routes "
        "through the same recording seam as \"Play Anyway\" and \"Try <source>\" right "
        "next to it in the same toast.",
        "Playing an episode had the mirror-image bug: it recorded the play "
        "(play count, History) BEFORE the stream's pre-flight check had confirmed "
        "the stream actually works — so a failed episode play still landed in "
        "History as watched. Recording now happens only after the pre-flight "
        "succeeds and mpv actually launches, matching how movies and live channels "
        "already worked.",
    ),
    test_steps=(
        "Disable a source that is the only working copy of some channel, so its "
        "sibling copy on another source fails to play; choose \"Reactivate & play\" "
        "from the failure toast — the channel plays AND now shows up in History "
        "with its play count bumped.",
        "Play an episode whose stream is unreachable (or briefly disconnect network) "
        "so the pre-flight check fails, then dismiss the failure toast without "
        "choosing Play Anyway — the episode does NOT appear in History as watched.",
        "Play a normal, working episode — it still appears in History and its "
        "season queue still auto-advances exactly as before.",
    ),
)

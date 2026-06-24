from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=62,
    version="0.9.0",
    date="2026-06-24",
    title="Resume works after re-watching a finished movie or episode",
    items=(
        "Fixed a bug where VOD playback always restarted from the beginning after you had "
        "previously finished a title and then started re-watching it. The root cause was a "
        "sticky 'completed' flag that blocked the resume logic even once you had accumulated "
        "new partial progress.",
        "Intended behavior change: starting to re-watch a title you already finished now "
        "un-marks it as 'completed' — it becomes a continue-watching item again. Finishing "
        "it a second time re-marks it complete.",
        "The fix also heals existing rows already stuck with a saved resume position and the "
        "completed flag both set — no re-watch required, the next play will resume correctly.",
    ),
    test_steps=(
        "Find a VOD movie. Start it, watch a few minutes, then close the player. Re-open it "
        "from the channel list or History — confirm it resumes at your saved position, not "
        "the beginning.",
        "Watch that movie all the way past ~90% so it is marked as watched (solid icon). "
        "Re-open it — confirm it starts from the beginning (no progress to resume).",
        "Start re-watching that finished movie and pause after a few minutes. Close and "
        "re-open — confirm it now resumes at the new position (it should no longer be stuck "
        "starting from the beginning after a prior completion).",
        "Confirm that 'Play from Beginning' still appears in the context menu when a movie "
        "has a saved resume position, and that using it starts from 0:00 without clearing "
        "the saved position.",
    ),
)

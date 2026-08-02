from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=218,
    version="0.18.1",
    date="2026-08-01",
    title="Startup maintenance pass no longer crash-loops on a busy library",
    items=(
        "The one-time title-cleanup migration could still crash mid-pass on a "
        "transient 'database is locked' even after #364 stopped it from being "
        "wrongly marked complete — so on a busy library it replayed its "
        "progress strip on every launch instead of finishing once. The "
        "startup EPG refresh and watch-alert checks now wait for any pending "
        "maintenance pass to finish before they start (instead of racing it), "
        "and the pass itself retries a batch a few times on a momentary lock "
        "instead of aborting the whole run.",
    ),
    test_steps=(
        "Launch the app after updating (with pending maintenance work, e.g. "
        "a fresh install or after a version bump) → the migration progress "
        "strip runs to completion in one pass, and the EPG guide / watch "
        "alerts refresh shortly after it finishes.",
        "Relaunch → the progress strip does NOT reappear (it only shows "
        "again if there is genuinely new maintenance work to do).",
    ),
)

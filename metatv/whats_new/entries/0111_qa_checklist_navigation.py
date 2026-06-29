from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=111,
    version="0.9.0",
    date="2026-06-28",
    title="QA checklist is navigable — deep-link test steps + clickable Addressed badge",
    items=(
        "Dev QA checklist (METATV_DEV): a test step can now carry a navigation "
        "target and renders a 'Go ▸' button that jumps the app straight to the "
        "view or content under test — no more hunting for the right screen.",
        "Deep-link targets: 'view:<name>' (browse/discover/recipe/epg/preferences), "
        "'settings:<tab>', and 'sample:<kind>' (vod/live/partial/series) which finds "
        "a representative channel and opens it in Browse + details.",
        "The 'Addressed PR #N' badge on a failed step is now clickable — it jumps to "
        "the addressing entry in the checklist (no-op when that entry isn't listed).",
    ),
    test_steps=(
        (
            "Click the 'Go ▸' button on this step — the app switches to the "
            "Discover view.",
            "view:discover",
        ),
        (
            "Click 'Go ▸' on this step — the app lands on Browse with a real "
            "movie open in the details pane (the app picks the sample channel).",
            "sample:vod",
        ),
        (
            "Click 'Go ▸' on this step — the Settings dialog opens on the "
            "Interface tab.",
            "settings:Interface",
        ),
        "A plain-text step (this one) shows NO 'Go ▸' button — backward compat.",
        "Mark a failed step that a later PR addresses, then click its green "
        "'Addressed PR #N' badge and confirm the checklist scrolls to the addressing "
        "entry.",
    ),
)

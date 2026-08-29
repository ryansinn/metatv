from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=415,
    version="0.53.0",
    date="2026-08-28",
    title="Version-matching no longer stops after the first 2,000 titles",
    items=(
        "The pass that teaches a title's other copies which film they are was "
        "crashing partway through and giving up.",
        "It saved its progress while still reading the list it was working "
        "from, which closed the connection underneath it - so it got through "
        "one batch and abandoned the rest.",
        "It now reads the list a page at a time and saves between pages, so a "
        "full run finishes however much there is to do.",
        "This is what groups a film's different versions together, so 'Other "
        "Versions' and duplicate-hiding both see more of the library.",
    ),
    test_steps=(
        "Browse enough movie or series titles to trigger enrichment, then "
        "check the log for 'post-drain sibling propagation failed' - it "
        "should not appear.",
        "Open a title that exists on more than one source and confirm 'Other "
        "Versions' lists the siblings.",
        "Refresh a large source and confirm the propagation line in the log "
        "reports adoptions without an error after it.",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=338,
    version="0.41.0",
    date="2026-08-23",
    title="MetaTV now ships its own typeface",
    items=(
        "The interface used whatever sans-serif your system happened to "
        "provide, so it looked different on every machine and none of those "
        "was the one it was designed against.",
        "It now ships Inter, chosen for having the largest x-height of the "
        "candidates and being clearest at 11–12px — which is where most of "
        "this interface lives.",
        "An icon set is bundled alongside it, ready for the icon work: "
        "Material Symbols, 48 glyphs, 7 KB.",
        "Both are in the repository with their licences and a script that "
        "rebuilds them, so they cannot go missing again.",
    ),
    test_steps=(
        "Launch the app and look at the sidebar headings, the row titles and "
        "the details pane → text renders in Inter, consistently, rather than "
        "in the system default.",
        "Compare a screenshot with one from the previous build → letterforms "
        "differ; sizes and layout do not shift.",
        "Check that nothing became clipped or wrapped: the bottom nav chips, "
        "the filter panel headings, the Settings dialog labels.",
        "Switch theme through Midnight, Graphite and Daylight → the typeface "
        "is the same in all three.",
        "If a packaged build is available, run it (not the source checkout) "
        "and confirm it also renders in Inter — that proves the font shipped "
        "inside the bundle rather than being picked up from the repo.",
    ),
)

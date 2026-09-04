from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=594,
    version="0.95.0",
    date="2026-09-04",
    title="A hidden stylesheet meets the contrast floor",
    items=(
        "The contrast-guard sweep that reconstructs stylesheets from source "
        "now resolves local variables, .format() templates, and "
        "\"\".join(...) calls — not just plain f-strings — so a sheet built "
        "across two statements is measured instead of silently skipped.",
        "That widened sweep found the four Sources sidebar action-button "
        "icons (toggle/edit/analyze/refresh) painting their own semantic hue "
        "as glyph text on a low-alpha tint of that same hue — as low as "
        "1.54:1 in Daylight. The glyph now reads in the app's own "
        "brightest-on-background text color; the colored tint and border "
        "still carry each action's hue.",
    ),
    test_steps=(
        "Switch to the Daylight theme, open the Sources sidebar section with "
        "at least one source listed.",
        "The toggle (●/○), edit (✎), analyze, and refresh icon buttons on a "
        "source row are all legible dark glyphs on their tinted background — "
        "none reads as a low-contrast colored-on-colored smear.",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=156,
    version="0.10.0",
    date="2026-07-28",
    title="Watch Alerts polish: ampersand, group labels, series disambiguation",
    items=(
        "The \"Movies & Series\" sub-section now shows a real ampersand (it "
        "previously rendered as \"Movies _Series\" because the button ate the \"&\" "
        "as a keyboard shortcut).",
        "When you have BOTH keyword rules and monitored series, the keyword rules "
        "now sit under a matching \"──── Watching for ────\" label, mirroring the "
        "\"──── Series ────\" divider so it is clear which rows are which.",
        "Two monitored series that clean up to the same title (e.g. two "
        "\"Fallout\") are now told apart: each row hovers to a tooltip listing its "
        "Language, Region and Source, and — only when there is an actual clash — "
        "shows a small dim tag (region, then language, then source) so you can see "
        "at a glance which is which.",
        "The Watch Alerts header dot now lights up when a monitored series gains a "
        "new episode too — not only for keyword matches — so a collapsed section "
        "still glows. \"Clear all\" stays tied to keyword matches (series are "
        "cleared per-row via \"Mark seen\").",
        "Fixed the section header so its subtle tint no longer stacks into a darker "
        "box behind the title and the Manage / Clear-all buttons.",
    ),
    test_steps=(
        "Open the sidebar Watch Alerts section with at least one keyword rule: the "
        "sub-section toggle reads \"Movies & Series\" with a real ampersand (not "
        "\"Movies _Series\").",
        "Add a keyword rule AND monitor a series: inside Movies & Series the rules "
        "sit under a \"──── Watching for ────\" label and the series under "
        "\"──── Series ────\"; with only one of the two groups, no extra label "
        "appears.",
        "Monitor two different series that clean to the same title (e.g. two "
        "\"Fallout\"): each row shows a small dim disambiguator, and hovering shows "
        "a tooltip with Language / Region / Source. A series with a unique title "
        "shows no disambiguator.",
        "Collapse the Watch Alerts section, then let a monitored series gain a new "
        "episode: the header dot lights green with a count, while \"Clear all\" "
        "does NOT appear (keyword-only).",
        "Look at any sidebar section header (Watch Alerts, Recommended, Sources): "
        "the title and link buttons no longer sit inside a darker box — the tint is "
        "even across the header strip.",
    ),
)

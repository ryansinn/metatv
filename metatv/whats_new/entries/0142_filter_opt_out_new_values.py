from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=142,
    version="0.9.0",
    date="2026-07-21",
    title="Filters now include new content by default (opt-out)",
    items=(
        "The \"Includes\" filter panel is now truly opt-out: a facet value that "
        "appears for the first time — e.g. a region code, language, or platform a "
        "freshly-refreshed source introduces — is INCLUDED automatically instead of "
        "being silently hidden because it wasn't in your saved selection.",
        "The app now remembers which facet values it has already shown you, so it "
        "can tell a brand-new value apart from one you deliberately deselected. "
        "Values you turned off stay off; only genuinely new ones default on.",
        "One-time un-hide: the first time you open the app after this update, each "
        "filter facet is reset to include everything currently present — so content "
        "that was being hidden by a stale saved selection (for example channels "
        "whose region code the app had never recorded) becomes visible again.",
        "New-values popup: after a source refresh or import surfaces new facet "
        "values, a dialog lists them grouped by facet — all checked (included) by "
        "default. Uncheck any you'd like to exclude and click Apply, or Include all "
        "to keep them.",
        "Fixed a latent bug where refreshing a source fed the wrong data shape into "
        "the filter panel and emptied every facet section until the next restart.",
    ),
    test_steps=(
        "Search \"Odyssey\" in the channel list before updating (or with a stale "
        "region selection): note some English (EN) results are missing. After this "
        "update's one-time un-hide, re-run the same search — the previously-hidden "
        "EN channels now appear.",
        "Open the \"Includes\" panel → Region on first launch after updating: every "
        "present region code is checked (nothing is left unchecked just because it "
        "wasn't in the old saved selection).",
        "Deselect a region value, then refresh a source that does NOT introduce new "
        "values: the value you deselected stays unchecked (a refresh does not "
        "re-check your deliberate deselections).",
        "Refresh/import a source that introduces a NEW facet value (e.g. a new "
        "region code or platform): a \"New filter values found\" popup lists it, "
        "checked by default; click Apply and confirm the value is included in the "
        "channel list.",
        "In that same popup, uncheck a new value and click Apply: that value is "
        "excluded from the filter (its section shows it unchecked) while the others "
        "stay included; the channel list reloads to match.",
        "Restart the app after the baseline has been established: no popup appears on "
        "a plain startup, and your filter selections (including any exclusions you "
        "applied) are preserved.",
    ),
)

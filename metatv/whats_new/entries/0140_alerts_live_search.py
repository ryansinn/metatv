from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=140,
    version="0.9.0",
    date="2026-07-21",
    title="Clicking an alert opens a live, editable search",
    items=(
        "Clicking a \"Watching for\" alert (or the Watch Queue's new-matches banner) "
        "now seeds the search box with the alert's keyword and runs a normal, editable "
        "search — a transparent view whose visible search/filter config is what "
        "produces the results — instead of an opaque fixed match set you couldn't tune.",
        "You can widen or narrow the results right there, and content hidden by your "
        "Global Exclusions is surfaced by the gold bar rather than silently dropped.",
    ),
    test_steps=(
        "In the Alerts section, click a \"Watching for\" rule: the view switches to "
        "Search with the rule's keyword in the search box and matching results listed "
        "— no opaque \"Alert: …\" chip.",
        "Edit the search text or a sidebar filter while there: the results update "
        "live, because it's a real search (not a frozen id-set).",
        "Click the Watch Queue's \"N new matches\" banner: it opens the same live "
        "search for the rule with the most new matches.",
    ),
)

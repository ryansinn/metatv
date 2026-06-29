from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=116,
    version="0.9.0",
    date="2026-06-28",
    title="New matched content is now visible & persistent",
    items=(
        "When a 'Watch for…' rule matches new content, the match no longer just "
        "flashes a toast and vanishes — it stays visible until you acknowledge it. "
        "A GREEN 🚨 badge with a count appears on the Alerts sidebar header (a "
        "global glance), the matching rule turns green, the matched titles are "
        "marked 🚨/green in the channel list, and a green line pins to the top of "
        "your Watch Queue: \"🔔 N new matches from your alerts →\".",
        "Click the Watch Queue line (or a watch-for rule) to open the new matched "
        "content, where each new item is flagged 🚨/green. Opening a matched series "
        "in the details pane lights its Alert button green too.",
        "Acknowledge matches when you're ready — nothing auto-acts. Right-click a "
        "matched item → 'Clear alert — I've seen this' to clear just that one, or "
        "use the 'Clear Alerts' button in the Watch Queue to clear them all. "
        "Clearing turns the green off on every surface at once (you don't have to "
        "actually watch anything).",
        "Colourblind-safe by design: the green is always paired with the 🚨 siren "
        "glyph and a count/text, never colour alone. The 🚨 'new match' marker is "
        "kept distinct from ✨ 'newly added'.",
    ),
    test_steps=(
        (
            "Add a 'Watch for…' rule (Alerts sidebar → + button) for a keyword that "
            "matches existing content, e.g. a movie you have. After the scan, the "
            "Alerts header shows a green '🚨 N' badge, the rule row turns green with "
            "'🚨 N new', and the matched titles show a 🚨 + green title in the channel "
            "list.",
            "alerts",
        ),
        (
            "Open the Watch Queue: a green line is pinned at the top ('… N new "
            "matches from your alerts →'). Click it — the channel list opens showing "
            "the matched content flagged 🚨/green.",
            "queue",
        ),
        "Open a matched SERIES in the details pane: its Alert/monitor button shows a "
        "green filled state. Right-click the same item in the list → 'Clear alert — "
        "I've seen this'. The green/🚨 disappears from the list, the sidebar badge "
        "count drops, the rule row returns to normal, and the details Alert button "
        "is no longer green.",
        (
            "With at least one unviewed match present, click 'Clear Alerts' in the "
            "Watch Queue header. The pinned green line and the global badge both "
            "disappear and all 🚨/green markers clear across every surface.",
            "queue",
        ),
    ),
)

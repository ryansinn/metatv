from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=228,
    version="0.19.0",
    date="2026-08-01",
    title="\"Play Next Episode\" button in the History sidebar",
    items=(
        "A series row in the History sidebar section now shows a \">>\" button "
        "when there's a next episode to watch — hover it to see which episode "
        "it targets (e.g. \"Play next episode: S02E05\").",
        "The target is the same smart resume ladder used elsewhere: continue an "
        "in-progress episode where you left off, or move on to the next one "
        "once the last-played episode is finished. No button appears when the "
        "series has no episodes yet or is already fully watched.",
        "Clicking it plays that episode immediately — no need to open the "
        "series and hunt for where you left off.",
    ),
    test_steps=(
        "Play a couple of minutes of a series episode, then open it again from "
        "History → the row shows a \">>\" button; hover it → the tooltip names "
        "the next episode (e.g. \"Play next episode: S01E02\").",
        "Click the \">>\" button → that episode starts playing directly.",
        "Finish watching every episode of a series (or open a series with none "
        "played yet) → its History row shows no \">>\" button.",
        "Click anywhere else on a History row (the title, year, or language "
        "chip) → the row still selects/opens exactly as before — the new "
        "button doesn't change existing row behavior.",
    ),
)

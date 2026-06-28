from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=98,
    version="0.9.0",
    date="2026-06-28",
    title="EPG Browse: working date changes, fixed time slots, honest coverage",
    items=(
        "Changing the Browse date (Tomorrow, or any later day) now correctly reloads "
        "the schedule to that day — previously it could look stuck on Today, because a "
        "broken Late Night slot left the list empty no matter which date you picked.",
        "Late Night is now 11 PM – 5 AM and correctly spans past midnight, so the "
        "early-morning programmes of the next calendar day finally show up (the old "
        "'11–3' slot was clipped at midnight and showed almost nothing).",
        "Morning is now 5 AM – 12 PM, closing the previous 3–6 AM gap; Afternoon "
        "(12–6) and Prime Time (6–11) stay contiguous with it.",
        "The empty-state coverage message is now honest: it reports how far the guide "
        "actually reaches CONTIGUOUSLY for the selected sources (stopping at the first "
        "real hole) instead of claiming it 'reaches tomorrow' when tonight's late-night "
        "block is missing.",
    ),
    test_steps=(
        "Open EPG → Browse. Change the date dropdown to Tomorrow (and a later day) and "
        "confirm the programme list RELOADS to that day's schedule (not stuck on Today).",
        "Select Late Night (11–5). Confirm programmes that START after midnight (e.g. a "
        "1–4 AM show on the next calendar day) appear — not just 11 PM–midnight rows.",
        "Select Morning (5–12) and confirm a 4–6 AM-ish programme that previously fell "
        "in no slot now shows; check Afternoon and Prime Time still list their windows.",
        "Pick a date/slot the guide does NOT cover (e.g. several days out, or Late Night "
        "when tonight's late block is missing). Confirm the empty-state names the REAL "
        "last-contiguous reach (e.g. 'guide currently reaches <today, time>') rather than "
        "implying coverage into tomorrow.",
    ),
    addresses=("e52_s1", "e54_s0"),
)

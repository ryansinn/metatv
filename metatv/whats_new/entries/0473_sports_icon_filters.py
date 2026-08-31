from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=473,
    version="0.62.0",
    date="2026-08-31",
    title="Pick a sport by its icon, and search within what you are looking at",
    items=(
        "The \"All Sports\" dropdown is gone. Sports are now a row of icon "
        "buttons — a ball, a racket, a helmet — each with the number of "
        "channels behind it, biggest first.",
        "Every sport has its own icon, including the multi-sport networks like "
        "Fox Sports 1 and Sky Sports News, which are grouped as \"General\" "
        "rather than \"Unknown\". They carry many sports, so having no single "
        "one is correct.",
        "There is a search box beside the filters. It narrows what you are "
        "already looking at — the lane and the sports you picked — instead of "
        "throwing you into a global search.",
        "Selecting no sports and selecting every sport both mean \"show "
        "everything\", and Clear now empties the row rather than lighting all "
        "of it up.",
    ),
    test_steps=(
        ("Open Sports. The sport filter should be a row of icons with counts, "
         "not a dropdown.", "view:sports"),
        "Click one sport and confirm the list narrows and the League filter "
        "offers only that sport's leagues.",
        "Click every sport in turn and confirm each shows a distinct icon — "
        "no two should look the same.",
        "Type into the search box and confirm it narrows within the lane you "
        "are on, and that the lane counts update to match.",
        "Press Clear and confirm the icons all switch off and the search "
        "empties.",
        "Restart the app and confirm your sport selection and search came back.",
    ),
)

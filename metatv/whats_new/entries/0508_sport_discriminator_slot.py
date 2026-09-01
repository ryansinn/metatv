from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=508,
    version="0.65.0",
    date="2026-09-01",
    title="Sports rows show whatever still tells them apart",
    items=(
        "Sports rows now carry a small leading mark: the sport's own icon — "
        "the same ones on the filter buttons above, so pressing the ball "
        "leaves exactly the rows wearing it.",
        "Once you filter to a single sport that icon would be the same on "
        "every row, so it changes to the region code instead, which is the "
        "thing still varying.",
        "And when nothing varies, the mark disappears entirely rather than "
        "leaving an empty column — the space goes back to the fixture name, "
        "which is what was getting cut off.",
    ),
    test_steps=(
        ("Open Sports with no sport filter and confirm each row shows its "
         "sport's icon on the left, matching the filter buttons.",
         "view:sports"),
        ("Click a single sport in the filter strip and confirm the icons are "
         "replaced by region codes (US, GB, ...)."),
        ("Confirm the region codes are letters, not flags."),
        ("Pick a sport where every remaining fixture shares one region, and "
         "confirm the mark disappears and the titles get wider rather than "
         "leaving a blank gap."),
        ("Switch back to no filter and confirm the icons return."),
        ("Open Browse and confirm ordinary channel rows are unchanged — no "
         "leading mark and no lost title width.", "view:browse"),
    ),
)

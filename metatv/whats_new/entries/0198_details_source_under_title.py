from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=198,
    version="0.16.0",
    date="2026-08-01",
    title="Details pane: 'Source:' now sits right under the title",
    items=(
        "Which source a title came from is header information — but it used to "
        "render below the whole metadata block, so on a title with rich metadata "
        "you had to read past the type, runtime, IMDb/TMDb ids and rating row to "
        "find it. The Source line (and the 🔞 Adult badge that shares its row) now "
        "sits directly beneath the title/year line.",
        "Everything the line does is unchanged: it still shows your source's icon "
        "and name, still shows '(source removed)' when the source is gone, and "
        "still copies the channel id to your clipboard when clicked.",
    ),
    test_steps=(
        "Select any movie or series with full metadata (poster, plot, cast). In the "
        "details pane confirm the 'Source: <icon> <name>' line is the first line "
        "under the title/year — above the tagline and above the "
        "type / runtime / IMDb / rating row.",
        "Click the Source line and paste somewhere: the channel id is on your "
        "clipboard, and the line's tooltip still shows that id.",
        "Select an adult-flagged title and confirm the 🔞 Adult badge appears on the "
        "same relocated line, beside the source name.",
        "Select a live channel and confirm the Source line is in the same new "
        "position and the pane layout is otherwise unchanged (no clipped or "
        "off-edge content at a narrow pane width).",
    ),
)

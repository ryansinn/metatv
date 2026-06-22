from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=9,
    version="0.6.0",
    date="2026-06-20",
    title="Playback readout shows which stream it's reporting",
    items=(
        "The live playback health readout now leads with the source's icon, so you can tell which stream the buffer/bitrate numbers belong to.",
        "With multiple windows open it shows the source icon next to the [position/total] marker; click to cycle between them.",
        "Closing one player window no longer blanks the readout — it keeps reporting on the streams still playing.",
    ),
)

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=475,
    version="0.64.0",
    date="2026-08-31",
    title="Download a movie to keep",
    items=(
        "Right-click a movie or an episode and choose Download. It is saved to "
        "your machine and stays there, so it plays when the source is having a "
        "bad night — or when you are not on the internet at all.",
        "A download gets out of the way the moment you press Play. Most "
        "sources allow one connection at a time, so a download that kept it "
        "would be a download that stopped you watching. It parks at the byte "
        "it reached and picks up from there when you stop.",
        "Interrupted downloads resume rather than start over — closing the app "
        "part-way through costs you nothing but the wait.",
        "Live channels are not offered: there is no end to download to. "
        "Recording one is a separate feature and is next.",
    ),
    test_steps=(
        ("Right-click a movie and choose Download; confirm the notification "
         "says it has started.", "view:list"),
        "Right-click a live channel and confirm Download is not offered.",
        "While a download is running, play something from the same source. "
        "The download should pause on its own and the stream should start.",
        "Stop playback and confirm the download resumes by itself rather than "
        "restarting from zero.",
        "Quit the app part-way through a download, reopen it, and confirm the "
        "download continues from where it stopped.",
        "Let a download finish, then confirm the file is in your downloads "
        "folder and plays in any video player.",
    ),
)

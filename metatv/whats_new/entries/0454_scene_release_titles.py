from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=454,
    version="0.58.0",
    date="2026-08-30",
    title="Titles that were torrent filenames are now titles",
    items=(
        "Over a thousand rows in your library showed something like "
        "\"Ceu.em.Chamas-Skyfire.2019.1080p.WEB-DL.x264.DUAL-COMANDO.TO\" "
        "where the name should be. That is the whole filename, dots and all.",
        "The name reader worked backwards from the end and gave up at the "
        "first thing it didn't recognise — and these names all END in a "
        "release-group tag it could never recognise, so it stopped "
        "immediately and kept the lot.",
        "It now reads them forwards instead, and finds where the title stops. "
        "That row is simply \"Ceu em Chamas-Skyfire\", from 2019, with FHD and "
        "H.264 picked up as attributes rather than left in the name.",
        "Channels ending in HDTV — \"NBA TV HDTV\", \"WFOR CBS 4 HDTV\" — drop "
        "the tag too and show an HD chip like every other HD channel.",
        "481 titles change. Nothing that was already correct moves: a name "
        "needs two unmistakable markers before any of this applies, which is "
        "why the film \"Opus\" is still called Opus and not mistaken for the "
        "audio codec of the same name.",
    ),
    test_steps=(
        ("Search Browse for \"Skyfire\". The result should read \"Ceu em "
         "Chamas-Skyfire\" — not a filename with dots in it.", "view:browse"),
        "Search for \"Atlas\", \"Beanie\" and \"Konusanlar\". Each should show "
        "a clean title; none should contain \"1080p\", \"WEB-DL\" or \"x264\".",
        "On one of those, check the chips: FHD should be there, and no chip "
        "should read WEB-DL — that says where a file came from, not how big it is.",
        "Search for \"NBA TV\". It should read \"NBA TV\" with an HD chip, not "
        "\"NBA TV HDTV\".",
        ("Search for \"Opus\" and confirm the 2025 film is still called Opus. "
         "Same for \"Gold\" and for WWE Raw — none of those words should have "
         "been mistaken for a technical tag.", "view:browse"),
        "Titles update on the next launch via the startup migration; if a row "
        "still looks like a filename, let it finish and check again.",
    ),
)

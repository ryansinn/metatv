from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=145,
    version="0.9.0",
    date="2026-07-22",
    title="Title bar now shows the running commit (and PR#) instead of a tagline",
    items=(
        "The window title dropped the \"IPTV Stream Organizer\" tagline. It now "
        "reads the running checkout's git identity, so you can always see which "
        "code you're looking at.",
        "On a named branch: \"MetaTV (main b3760bd)\". When launched to test a PR "
        "via run.sh <PR#>: \"MetaTV (b3760bd PR#298)\". Uncommitted local edits add "
        "a \"*\" after the commit (e.g. b3760bd*).",
    ),
    test_steps=(
        "Launch normally (./run.sh) on main: the title bar reads "
        "\"MetaTV (main <shortsha>)\" — no \"IPTV Stream Organizer\" tagline.",
        "Launch a PR with run.sh <PR#> (e.g. ./run.sh 298): the title reads "
        "\"MetaTV (<shortsha> PR#298)\".",
        "Make an uncommitted edit to a tracked file, relaunch: a \"*\" appears after "
        "the commit hash (e.g. \"MetaTV (main <shortsha>*)\").",
    ),
)

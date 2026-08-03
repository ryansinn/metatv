"""What's New entry: one film split across several identities, so "Other
versions" could not group its copies."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=284,
    title="Copies of the same film find each other again",
    items=(
        "A film could be split into several separate identities, so its own "
        "copies did not recognise each other and \"Other versions\" looked "
        "empty or incomplete — \"The Lobster\" existed as three, and only one "
        "of them knew what it was.",
        "The cause: two different rules for deciding whether two listings are "
        "the same title. The rule used to match copies was built for raw "
        "channel names, and it stripped words that had already been cleaned "
        "off — turning \"Blade Runner 2049\" into \"Blade Runner\" and merging "
        "a 2017 sequel with the 1982 original, and reading \"WWE: Unreal\" as "
        "just \"Unreal\".",
        "With unrelated films sharing a pile, the app could no longer tell "
        "which one a copy belonged to, so it safely refused to link any of "
        "them. Both rules are now one rule. Measured against a real library, "
        "this correctly linked 498 listings that had been stuck, and mislinked "
        "none.",
        "Separately, when the app looked up a title and learned its id, that "
        "answer stopped at the one listing it looked up. It now passes what it "
        "learned to that title's other copies straight away.",
        "Genuine remakes are still left alone. Ten different \"A Christmas "
        "Carol\" films stay ten films — the app links copies only when the "
        "evidence points to exactly one answer.",
        "Existing libraries are re-checked once on the next launch.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Launch and let the \"Linking language/quality variants by shared "
        "title\" pass run in the Migration Center. It completes without error.",
        "Open a film you own several copies of (e.g. \"The Lobster\"). The "
        "details pane's \"Other versions\" lists the other copies rather than "
        "showing one lonely entry.",
        "Find a sequel whose title ends in a number — \"Blade Runner 2049\" is "
        "the clearest. Its versions group with each other and NOT with the "
        "1982 \"Blade Runner\", which stays a separate title.",
        "Search a title with many genuine remakes (\"A Christmas Carol\"). "
        "They remain separate films — they must NOT all collapse into one card.",
        "Browse a Movies list you have not opened this session, wait for the "
        "\"Updating N titles…\" toast to finish, and confirm the list settles "
        "and re-groups without a restart.",
    ),
)

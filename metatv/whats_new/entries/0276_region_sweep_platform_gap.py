"""What's New entry: the region sweep missed a whole class of listings because
it consulted the wrong platform vocabulary."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=276,
    title="More wrongly-labelled countries cleaned out",
    items=(
        "The country cleanup shipped a moment ago missed a group of listings: a "
        "Scandinavian copy of \"Ballerina\" was still labelled Spain, and "
        "tagged Spanish with it.",
        "The cleanup checked a short list of streaming brands when deciding "
        "whether a listing's prefix was a platform rather than a country. The "
        "app classifies platforms from a much longer list, and codes like "
        "\"SC\" were only on the longer one — so those listings slipped "
        "through. It now uses the same list everything else does.",
        "Around 4,700 more listings are corrected on next launch, and their "
        "invented language tags go with them.",
        "Listings that state their own country are still kept, including ones "
        "that say it in the title rather than the category — \"SC - Monk (US)\" "
        "keeps US.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Launch and watch for \"Correcting mislabelled regions\" running again "
        "(it re-runs once for this fix). Logs show \"cleared N mislabelled "
        "regions\".",
        "Open the Scandinavian \"Ballerina\" (4K-SC, category NORDIC FILMS) — "
        "it no longer shows Spain, and its Tags no longer list Spanish.",
        "Confirm a title that names its own country in the TITLE is untouched: "
        "\"SC - Monk (US)\" still shows US.",
        "Confirm live channels are untouched: Sky Sports still shows UK.",
        "Relaunch once more — the cleanup does not run a third time.",
    ),
)

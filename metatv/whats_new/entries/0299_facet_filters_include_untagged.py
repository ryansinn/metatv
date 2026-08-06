"""What's New entry: facet filters were excluding content they had nothing to
say about, which culled most of the library."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=299,
    title="Filters no longer hide everything they can't describe",
    items=(
        "Unticking one box in a filter section did not remove that one thing — "
        "it removed everything the app had never tagged on that whole facet. "
        "Untick a single subtitle language and you lost the 99.6% of your "
        "library with no subtitle information at all.",
        "The cause: each section compiled to \"must carry one of the ticked "
        "values\", which cannot tell \"has a value you rejected\" apart from "
        "\"has no value here\". Tags are captured generously and deliberately "
        "sparsely — most titles carry nothing on most facets — so that turned "
        "a narrowing action into a cull.",
        "Measured on a real 489,954-channel library, switching ONE facet on "
        "left: dub 12 titles, subtitle 1,834, format 2,952, category 5,488, "
        "quality 31,378, platform 38,347, genre 129,995. Those are now 489,952 "
        "/ 489,088 / 489,954 / 489,687 / 489,954 / 489,856 / 489,363.",
        "A facet filter now means what it looks like it means: show the values "
        "I ticked, and don't hide things this facet has nothing to say about. "
        "Unticking a value you actually carry still excludes you, exactly as "
        "strictly as before — \"It's Always Sunny\" can still be hidden by "
        "unselecting English or Comedy, which is where the line belongs.",
        "The details-pane metadata chips are unchanged: clicking a genre still "
        "means \"show me ONLY this\", so it stays strict.",
    ),
    version="0.27.0",
    date="2026-08-05",
    test_steps=(
        "Open Search with every filter section fully selected and note the "
        "result count — it should be your whole visible library.",
        "Open SUBTITLE LANGUAGE and untick one language. The count should drop "
        "by roughly the number of titles carrying that subtitle — not to a few "
        "hundred results.",
        "Re-tick it, then untick one DUB LANGUAGE. Same: a small drop, not a "
        "collapse to a handful.",
        "Search for \"Always Sunny\". It should now appear with the filters in "
        "their normal state.",
        "With it visible, open GENRE and untick Comedy. It should disappear — "
        "deliberate exclusion still works.",
        "Re-tick Comedy, then untick English under LANGUAGE. It should "
        "disappear again.",
        "Open a title's details and click one of its genre chips. That is a "
        "strict \"only this genre\" filter and should still show only titles "
        "actually tagged with it.",
        "Check the \"hidden by search filters\" count above the list: it should "
        "only count titles a filter actually rejected, and clicking \"show\" "
        "should reveal exactly that many.",
    ),
)

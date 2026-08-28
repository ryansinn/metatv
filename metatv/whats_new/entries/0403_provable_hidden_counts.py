from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=403,
    version="0.53.0",
    date="2026-08-28",
    title="'Hidden by filters' claimed thousands it could not account for",
    items=(
        "The gold bar tells you how many results a filter is holding back. On a "
        "big list it worked that out by fetching two pages - what you can see, "
        "and the same list with one filter lifted - and subtracting their sizes.",
        "Both pages stop at 5,000. Once both were full the subtraction stopped "
        "meaning anything, so the bar just claimed 5,000 hidden. If the filter "
        "was actually hiding nothing, you got 'about 5,000 hidden' and a reveal "
        "button that revealed nothing.",
        "It now compares which titles are in each page rather than how many. "
        "Anything present with the filter lifted and missing without it was "
        "provably hidden by that filter - so the number is real at every size, "
        "and it is zero when nothing is being held back.",
        "On a real library this changed a keyword filter's report from 'about "
        "5,000 hidden' to 902, and a filter matching nothing from 'about 5,000' "
        "to none at all. The bar still says 'at least' when the page was full, "
        "because a full page cannot prove there is nothing beyond it.",
    ),
    test_steps=(
        "Open a view with more than 5,000 results and add a Global Exclusions "
        "keyword that matches nothing - the gold bar should show no keyword "
        "segment at all, not 'about 5,000 hidden'.",
        "Change it to a keyword that matches a lot - the bar should show a "
        "specific number prefixed with 'at least', and the reveal button should "
        "actually reveal that many.",
        "Narrow the view under 5,000 results and confirm the count shows as an "
        "exact number with no 'at least' prefix.",
        "Scroll a long filtered list to the bottom and confirm no row appears "
        "twice and none is skipped between pages.",
    ),
)

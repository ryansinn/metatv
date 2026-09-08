from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=627,
    version="0.103.0",
    date="2026-09-07",
    title="A stream that will not play offers to refresh its source",
    items=(
        "Stream links carry provider-side tokens that expire, so a channel that "
        "played yesterday can stop playing until its source is refreshed — and "
        "the app never suggested it. When a stream fails to open and its source "
        "was last refreshed more than a day ago, the failure toast now says so "
        "(\"Last refreshed 3 days ago — its stream links may have expired\") and "
        "offers a \"Refresh <source>\" button for that one source. Nothing "
        "refreshes on its own.",
        "Housekeeping: the advisory-error helper's docstring now describes its "
        "one real consumer, the failover sweep.",
    ),
    test_steps=(
        "Play a channel from a source last refreshed more than a day ago that "
        "fails to open → the toast names the source, says when it was last "
        "refreshed, and offers Refresh <source>.",
        "Click that button → only that source starts refreshing (the Sources "
        "strip shows it); nothing else refreshes.",
        "A failure on a source refreshed within the last day → no Refresh "
        "button on its toast.",
    ),
)

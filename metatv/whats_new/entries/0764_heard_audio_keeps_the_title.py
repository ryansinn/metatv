from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=764,
    version="0.201.0",
    date="2026-10-31",
    title="A copy heard in your language keeps its title visible",
    items=("When every copy of a title sits under an excluded language, but a stream check "
           "heard one copy in another language (an English film filed under NL), that copy "
           "now stands for the title in the collapsed list. Before, a better-quality "
           "excluded copy could win the slot and the whole title disappeared.",
           "EPG On now shows those channels too, matching the channel list.",
           "Scrolling past the first page of the channel list now keeps Hide watched and "
           "keyword exclusions; later pages used to bring those rows back.",),
    test_steps=("In Global Exclusions, exclude a language whose channels you have played or "
                "probed and found to be in English (the details pane's audio line says "
                "English). With variants collapsed, search the title — it shows, and its "
                "row is the English-audio copy.",
                "Open EPG → On now with the same exclusion — a live channel under that "
                "prefix that was measured in another language is listed.",
                "Turn on Hide watched and scroll a large list past the first page — no "
                "watched title (✓) appears further down.",),
)

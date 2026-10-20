from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=760,
    version="0.197.0",
    date="2026-10-20",
    title="More genre tidying: social dramas, translations, and non-genres removed",
    items=("Arabic and Persian \"social\" series now count as Drama (with Crime when the "
           "provider also says \"police\").",
           "About forty more provider genres are translated into the genres they name — "
           "spy, news, cabaret, puppet shows, nature documentaries and so on.",
           "Values that are not genres at all — format words like \"Film\", episode labels, "
           "plot summaries — no longer appear in the Genre filter; GAİN is listed as a "
           "platform instead."),
    test_steps=("Launch, let the tidying finish, then open the Genre filter — no 'Social', "
                "'Film' or long sentence rows remain; Drama's count has grown.",),
)

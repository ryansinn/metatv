from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=791,
    version="0.227.0",
    date="2026-11-01",
    title="Exclusions: hide genres and channel categories, shorter dialog",
    items=("Global Exclusions has a Genres section. Choose whether an excluded genre hides only titles "
           "that are entirely that genre (the default, so a Horror-Comedy stays when you exclude "
           "Horror) or every title that carries it.",
           "Channel Categories (Sports, News, Kids, Music, Adult, 24/7, Religious) replace the old "
           "Content Types list, matching however a source spells its headers. Kids and Religious "
           "exclusions carry over and now apply in Discover and Recommendations too.",
           "Languages and Platforms start collapsed with a summary and remember how you leave them; "
           "categories and genres sit in a grid, and rarely-used genres fold behind \"Show N more\".",
           "A country listed under two codes (Chile CL and CHL) is one row.",),
    test_steps=("Open Exclusions — Languages and Platforms are collapsed with \"N groups · N excluded\"; "
                "expand Languages, close and reopen the dialog — it stays expanded.",
                "Channel Categories shows Kids and Religious checked (carried over from Content Types).",
                "In Genres check Horror with \"only\" selected, OK — a pure horror film is gone from "
                "Movies, a horror-comedy is still there.",
                "Switch Genres to \"any\", OK — the horror-comedy is gone too; uncheck Horror to restore.",
                "Click \"Show N more\" under Genres — the small genres appear; \"Sci-Fi & Fantasy\" reads "
                "with an ampersand.",
                "Search the box for \"chile\" — one Chile row showing [CL·CHL].",),
)

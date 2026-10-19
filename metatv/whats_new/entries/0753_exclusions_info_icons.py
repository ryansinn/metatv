from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=753,
    version="0.190.0",
    date="2026-10-19",
    title="Global Exclusions' help marks use the app's info icon",
    items=("The small help marks beside each Global Exclusions heading (Languages, "
           "Platforms, Content Types, your categories) are the app's info icon instead of "
           "a typed ⓘ character; hovering one still explains the section.",),
    test_steps=("Open Global Exclusions — each section heading has an info icon beside it; "
                "hover it and the explanation appears.",),
)

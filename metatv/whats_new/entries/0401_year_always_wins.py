from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=401,
    version="0.52.0",
    date="2026-08-27",
    title="Titles with a word after the year kept the year in their name",
    items=(
        "Sources often write a marker after the year - 'Christmas At Castle "
        "Hart (2021) Hallmark'. The app only looked for a year at the very end "
        "of a name, so anything after it hid the year completely.",
        "Those titles ended up with no year at all, and with '(2021) Hallmark' "
        "still inside the title. That stopped them matching their own other "
        "copies, and left them lumped in with unrelated films of the same name "
        "that also had no year.",
        "2,092 titles were affected, led by 'sinhronizirano' (385), 'Hallmark' "
        "(322) and 'Polski' (176) - dub markers, studios and languages rather "
        "than anything belonging in a title.",
        "The year is now picked up wherever it appears. The word after it is "
        "only moved out of the title when the app can say what it is - a "
        "studio, a dub or subtitle marker, a genre, a rating or a quality. "
        "Anything it does not recognise stays put, because it may be a real "
        "part of the title ('FBI (2024) Reboot'), and those still gain a year.",
        "Existing titles are re-read once on the next launch. Checked against "
        "all 466,061 names first: 2,038 gain a year and none lose one.",
    ),
    test_steps=(
        "On the next launch let the one-time 'Re-reading titles' pass finish.",
        "Search for a Hallmark film - the row should now read 'Christmas At "
        "Castle Hart' with the year shown separately, not '(2021) Hallmark' "
        "inside the title.",
        "Open one and check 'Other Versions' - copies that used to look like "
        "separate films should now be listed together.",
        "Find a title whose name genuinely ends in a word after the year that "
        "is part of the title, and confirm that word is still there.",
        "Confirm titles where the provider appended an actor in capitals still "
        "show that actor and are otherwise unchanged.",
    ),
)

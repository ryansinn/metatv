from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=346,
    version="0.41.0",
    date="2026-08-24",
    title="Titles no longer disappear when their best copy is excluded",
    items=(
        "With \"Collapse quality/language versions\" on, a title showed one row "
        "chosen from all its copies — and that choice was made before Global "
        "Exclusions were applied. If the best copy happened to be one you had "
        "excluded, the row was dropped and the whole title vanished, including "
        "copies you had never excluded.",
        "Aladdin was the reported case: 15 copies, the 4K German one won the "
        "slot, German is excluded, and all fifteen disappeared — including the "
        "Disney+ and English copies.",
        "The choice now skips copies you have excluded, so a title shows its "
        "best AVAILABLE copy instead of nothing. Measured on this library: "
        "18,392 titles come back.",
        "A title whose every copy is excluded still stays hidden, and the "
        "\"N hidden by Global Exclusions\" count and the ×N badge are unchanged.",
        "It also stops putting forward a copy whose REGION you have excluded "
        "when a cleaner one exists — Aladdin was showing its German Disney copy "
        "because that copy's language tag (MULTI) is not excluded even though "
        "its region (DE) is. An equal-quality English copy is now preferred. "
        "2,497 titles put forward a better copy as a result.",
    ),
    test_steps=(
        "Settings → Interface → Channel List → tick \"Collapse quality/language "
        "versions into one row\". Search for a title you know has copies in an "
        "excluded language — e.g. Aladdin, Superman, Wicked.",
        "The title appears, showing a copy carrying none of your excluded "
        "codes — for Aladdin, the English 4K one, not the German Disney copy "
        "(whose region is DE even though its language tag is MULTI).",
        "Find a title whose ONLY remaining copy is from an excluded region → "
        "it is still shown, not hidden. Demoting a copy must never hide it.",
        "Right-click → Show N versions → the full variant list still shows the "
        "same total it did before, excluded copies included.",
        "The gold \"N hidden by Global Exclusions — show\" bar still reports a "
        "count, and clicking \"show\" still reveals the excluded copies.",
        "Find a title where EVERY copy is in an excluded language → it stays "
        "hidden, as it should, and is counted in the gold bar.",
        "Untick collapse → the individual rows behave exactly as before.",
    ),
)

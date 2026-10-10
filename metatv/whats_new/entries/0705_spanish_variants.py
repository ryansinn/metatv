from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=705,
    version="0.145.0",
    date="2026-10-09",
    title="Castilian Spanish stays Spanish; Latin American Spanish is its own",
    items=(
        "A stream's audio or subtitles tagged es-ES (castellano) read as Spanish; "
        "es-419 and Latin American country codes read as Latin American Spanish, "
        "es-MX as Spanish (Mexico), and pt-BR / pt-PT as Portuguese (Brazil) / "
        "(Portugal) — the same names the language filter already uses.",
    ),
    test_steps=(
        "Play a Spain-sourced title with castellano audio — Details' Audio reads "
        "Spanish.",
        "Play or probe a Latin American title (es-419/es-MX audio) — it reads Latin "
        "American Spanish / Spanish (Mexico), and filtering by that language finds it.",
    ),
)

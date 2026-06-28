from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=88,
    version="0.9.0",
    date="2026-06-28",
    title="Fix: 'Filtered Variants' header styling (stylesheet parse error)",
    items=(
        "The 'FILTERED VARIANTS' header in the details pane's Other Versions "
        "section had a malformed stylesheet (a stray extra brace), so Qt dropped "
        "its styling and logged 'Could not parse stylesheet' warnings. The header "
        "now renders correctly and the warnings are gone.",
    ),
    test_steps=(
        "Open a movie/series with multiple source variants that include filtered "
        "(blocked-prefix) ones so the 'FILTERED VARIANTS' collapsible header "
        "appears in the details pane. The header should render in the muted bold "
        "style (not default button styling), and the app log should show no "
        "'Could not parse stylesheet' warnings.",
    ),
)

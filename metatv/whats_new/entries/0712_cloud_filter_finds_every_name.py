from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=712,
    version="0.152.0",
    date="2026-10-10",
    title="A facet's Filter box finds every name",
    items=("Typing in a drilled-in cloud's Filter box (e.g. Cast) now also searches the "
           "whole library, so people below the top-300 cutoff show up.",
           "Search results name each tag's facet ('William Wyler · Directing'), since "
           "Cast and Directing share a colour."),
    test_steps=("Open Recipe → click Cast, type 'wyle' in the Filter box — Noah Wyle appears "
                "even though he is not in the top 300.",
                "Clear the box — the cloud returns to the top 300.",
                "Type 'wyle' in 'Search tags across all facets' — each result names its facet "
                "(Cast or Directing)."),
)

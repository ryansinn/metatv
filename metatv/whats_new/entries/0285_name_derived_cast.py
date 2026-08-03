"""What's New entry: actors named in a provider's filename are now searchable
instead of being thrown away."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=285,
    title="Actors named in a listing's title are no longer discarded",
    items=(
        "Some sources put an actor at the end of a listing — \"Adaptation. 4K "
        "(2002) NICOLAS CAGE\". The app already trimmed that off the displayed "
        "title so the title read cleanly, and then dropped it entirely. It is "
        "now kept.",
        "These appear under Tags as \"Named in Title\", separate from Cast & "
        "Crew. That separation is deliberate: this is whatever the source typed "
        "in a filename, not verified credits, so it is marked as the guess it "
        "is — a source's typo must never look like a confirmed credit.",
        "Only names that actually look like names are kept. Roughly half of "
        "what sources put in that position is not a person at all — \"POLSKI\", "
        "\"4K\", \"DOKUMENT\", \"DUBBING\", \"PIXAR\" — and filing those under "
        "people would have made the filter useless.",
        "Billed pairs stay together (\"Abbott & Costello\"), two names separated "
        "by a comma become two people, and a trailing note like \"(ENG-SUB)\" "
        "is ignored.",
        "Existing libraries pick these up on the next launch's re-scan.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Launch and let the name re-scan and tag passes finish in the "
        "Migration Center.",
        "Find a movie whose source title ends in an actor's name (e.g. one "
        "ending \"NICOLAS CAGE\" or \"LOUIS DE FUNES\"). Open it: the title "
        "shown is still clean, without the actor appended.",
        "In that title's Tags section there is a \"Named in Title\" group "
        "listing the actor, styled as a low-confidence chip.",
        "Click that chip — the results list filters to titles naming that "
        "person.",
        "Confirm the Cast & Crew section is unchanged: the name must NOT have "
        "been added there as though it were a verified credit.",
        "Check a title whose source appended \"POLSKI\", \"4K\" or \"DOKUMENT\" "
        "— those must NOT appear as people.",
    ),
)

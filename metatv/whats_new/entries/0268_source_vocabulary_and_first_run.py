"""What's New entry for the vocabulary unification (Provider → Source in every
user-facing string), the Select/Unselect All bulk toggles in the New Filter
Values dialog, and the first-run hand-off to Discover."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=268,
    title="One word for a source, bulk filter toggles, and a first run that goes somewhere",
    items=(
        "The app called the same thing a \"provider\" in some places and a "
        "\"source\" in others — sometimes in the same window. It is a Source "
        "everywhere now: menus, buttons, dialog titles, status messages and "
        "tooltips. (\"Provider\" survives only inside the code, where it names "
        "a database record.)",
        "The New Filter Values dialog now has Select all / Unselect all. A new "
        "source can introduce hundreds of values at once, and the useful "
        "starting point is often \"exclude everything, then add back the few I "
        "want\" — which previously meant unchecking them one at a time.",
        "A brand-new install now lands on Discover once the first source "
        "finishes importing. Discover was already the intended home view, but "
        "someone with no sources had no content, so nothing ever took them "
        "there — they were left on an empty channel list. It only happens on a "
        "genuine first run, and never if you have already picked a view "
        "yourself.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Open the File menu — it reads \"Add Source…\", not \"Add Provider…\". "
        "Open Sources and click a source: the form field above the name box "
        "reads \"Source Name\", and the delete button says \"Delete Source\".",
        "Hover the tooltips in Sources (enable/disable, refresh, edit) and in "
        "the EPG tab — none of them say \"provider\".",
        "Refresh a source so new filter values appear. The New Filter Values "
        "dialog shows Select all / Unselect all above the list; Unselect all "
        "clears every checkbox in every section, Select all re-checks them.",
        "First-run check (needs a clean profile — move ~/.config/metatv aside "
        "first): launch with no sources, confirm the empty state, add a source "
        "and wait for the import. When channels finish loading the app moves "
        "itself to Discover.",
        "Same clean-profile run, but this time click EPG (or Recommended) while "
        "the import is still going: the app leaves you where you chose and does "
        "NOT jump to Discover when loading finishes.",
    ),
)

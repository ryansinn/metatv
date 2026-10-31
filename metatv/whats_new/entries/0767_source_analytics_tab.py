from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=767,
    version="0.204.0",
    date="2026-10-31",
    title="Source analytics moved into the Sources editor",
    items=("The Analyze button and its separate screen are gone. Each source now has an "
           "Analytics tab beside Summary, Connection and Settings that answers \"is this source "
           "worth keeping?\": what only it carries, how much your other sources share with it, "
           "its catalogue and guide coverage, how its server addresses are doing, and the "
           "prefixes the name parser does not recognise yet.",
           "\"The same title\" now means the same thing it does everywhere else in MetaTV, for "
           "films, series and live channels — not just live channel names — and the tab loads in "
           "about three seconds instead of a minute.",
           "\"Browse them\" opens the titles only that source carries in Search.",
           "Disabled and expired sources stay in the comparison, greyed and labelled, and when "
           "another source carries almost everything this one does, the tab says so.",),
    test_steps=("Open Sources, pick a source and click the Analytics tab — within a few seconds "
                "Only here, Shared with your other sources, Catalogue & guide, Server addresses "
                "and Unrecognized prefixes all fill in.",
                "In Shared, an expired or disabled source's rows are greyed and say \"(expired)\" "
                "or \"(disabled)\"; bars at 98% are the same colour as bars at 30%.",
                "Click \"Browse them\" under Only here — the channel list opens with an \"Only "
                "on <source>\" chip and shows titles no other source has; clear the chip and the "
                "list returns to normal.",
                "Switch to another source while on Analytics — the tab reloads for that source "
                "without re-waiting for the Shared section.",
                "The Summary tab's action bar no longer has an Analyze button.",),
)

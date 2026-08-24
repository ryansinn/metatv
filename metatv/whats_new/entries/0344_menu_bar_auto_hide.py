from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=344,
    version="0.41.0",
    date="2026-08-24",
    title="Hide the menu bar until Alt — if you want to",
    items=(
        "New option: the menu bar can hide itself until you press Alt. "
        "It is OFF by default — the menu bar stays exactly where it is unless "
        "you go and ask for this.",
        "Alt toggles it: press once to show, again (or Escape) to hide. "
        "Alt+F still just opens the File menu, as it always did.",
        "The way back does not depend on the menu bar. Tools ▸ \"Menu bar "
        "always visible\" turns it off again, and the header's Tools button "
        "opens that same menu whether the bar is showing or not.",
        "Worth knowing before you switch it on: the header surfaces only "
        "Tools, so File, View, Layout, Style and Buffer all go behind the Alt "
        "press with it.",
        "Not offered on macOS, where the menu bar is the system bar at the top "
        "of the screen rather than part of the window — there is nothing there "
        "to hide.",
    ),
    test_steps=(
        "Launch → the menu bar is visible, and Alt does nothing to it. This is "
        "the default and must not have changed.",
        "Settings → Interface → Appearance → tick \"Hide the menu bar until Alt "
        "is pressed\" → OK. The menu bar disappears immediately.",
        "Press Alt → the menu bar appears. Press Alt again → it hides. Press "
        "Alt then Escape → it hides.",
        "With the bar hidden, press Alt then F → the File menu opens and the "
        "bar does NOT toggle out from under it.",
        "With the bar still hidden, click the header's Tools button → the menu "
        "opens, and \"Menu bar always visible\" is unticked at the bottom.",
        "Tick it → the menu bar comes back and stays. Re-open Settings → the "
        "checkbox is unticked, matching.",
        "Quit and relaunch with the option on → the bar starts hidden, and "
        "does not flash into view first.",
    ),
)

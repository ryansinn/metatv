"""MetaTV's own "Midnight" neutral ramp — from the design document.

Lives beside ``radix.py`` rather than inside it for the same reason
``gruvbox.py`` does: radix.py is vendored and carries "DO NOT hand-edit —
regenerate from upstream", so a hand-authored scale pasted in there is lost at
the next regeneration.

``docs/design/v3-metatv-redrawn.html`` names its own neutral ramp, and it is
genuinely cooler than any Radix grey: ``--sunken #090C10`` through
``--line #2E3742`` carry a blue cast that slate does not. The closest Radix
matches sit 4-9 units away EACH, always in the direction of "less blue" —
which is precisely why the previous Midnight, built on slate, drifted into
reading as a second Graphite.

The six surface anchors and the three text anchors are the design's verbatim
values. Steps 7-9 are interpolated between ``--line`` and ``--t3``; the design
does not name them because nothing in it uses them.

No LIGHT variant: the design specifies one, but this ramp exists for the dark
theme it names, and inventing light values would be guessing at the very thing
the document was consulted to avoid.
"""

MIDNIGHT_DARK: tuple[str, ...] = (
    "#090c10",   #  1  --sunken   app ground
    "#0e1116",   #  2  --ground
    "#151a21",   #  3  --surface  section card
    "#1c222b",   #  4  --raised   header band
    "#212831",   #  5  --hair
    "#2e3742",   #  6  --line
    "#454e59",   #  7  interpolated
    "#5c6570",   #  8  interpolated
    "#727c88",   #  9  interpolated
    "#89939f",   # 10  --t3       muted text
    "#a7b2c0",   # 11  --t2       body text
    "#e9eef5",   # 12  --t1       bright text
)

#: The alpha companion, DERIVED from the ramp above rather than authored: each
#: step is the translucent colour that composites over step 1 to give that
#: step's opaque value. A Radix scale ships both, and the loader looks up
#: ``<hue>A`` for every ``{neutralA.N}`` reference, so a ramp without one
#: cannot be used as a palette's neutral.
MIDNIGHT_A_DARK: tuple[str, ...] = (
    "#00000000",   #  1  transparent — step 1 IS the ground
    "#d0d3ff06",   #  2
    "#b2d1ff12",   #  3
    "#b1cfff1d",   #  4
    "#b7d7ff23",   #  5
    "#badaff35",   #  6
    "#cde4ff4e",   #  7
    "#d8eaff66",   #  8
    "#daebff80",   #  9
    "#dfeeff99",   # 10
    "#e0edffbc",   # 11
    "#f3f8fff4",   # 12
)

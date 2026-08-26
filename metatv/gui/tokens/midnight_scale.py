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

The surface anchors and the three text anchors are the design's verbatim
values. Steps 7-9 are interpolated between ``--line`` and ``--t3``; the design
does not name them because nothing in it uses them.

``--ground`` (#0E1116) is deliberately NOT a step. The design sets it one hair
above ``--sunken``, which is fine in a document but leaves MetaTV's list and
its surrounding chrome at 1.036:1 — one undifferentiated dark field, the exact
defect ``test_the_list_is_distinguishable_from_the_app_chrome`` was written for
after Daylight shipped at 1.023:1. Steps 1-3 therefore take sunken/surface/
raised, which are the three the app actually has to tell apart.

No LIGHT variant: the design specifies one, but this ramp exists for the dark
theme it names, and inventing light values would be guessing at the very thing
the document was consulted to avoid.
"""

MIDNIGHT_DARK: tuple[str, ...] = (
    "#090c10",   #  1  --sunken   the LIST — content recessed into the shell
    "#151a21",   #  2  --surface  the chrome around it
    "#1c222b",   #  3  --raised   the section card
    "#212831",   #  4  --hair
    "#252d38",   #  5  interpolated
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


# ── The design document's accents ────────────────────────────────────────────
# docs/design/v3-metatv-redrawn.html gives ONE value per accent, not a ramp:
# --accent #7FA3E1, --ok #3FBF7F, --warn #E0A030, --err #E5484D. The palette
# needs steps 4, 10 and 11 of each.
#
# Each ramp takes its HUE and its step-11 value from the design, and its
# LIGHTNESS and SATURATION progression from the nearest Radix ramp, scaled so
# step 11 lands on the design's value exactly. Scaled rather than shifted: an
# additive shift crushed the low steps of --err to pure black and broke amber's
# ordering.
#
# Cross-check that this is sound rather than merely plausible: the design also
# names --accent-soft #132743, which is a step-4 value and was NOT used as an
# input. The derivation lands on #12274c — a distance of 9. It reproduces a
# value the document specifies independently.
#
# WARN is non-monotonic in lightness at steps 9-10. That is inherited, not a
# defect: Radix's own amber dips there (0.62 -> 0.52) because its solid step is
# a bright yellow.
MIDBLUE_DARK: tuple[str, ...] = (
    "#10141b",   #  1
    "#141921",   #  2
    "#17243a",   #  3
    "#12274c",   #  4
    "#152e5a",   #  5
    "#253f6c",   #  6
    "#365181",   #  7
    "#41629a",   #  8
    "#2e66c6",   #  9
    "#5685d7",   # 10
    "#7fa3e1",   # 11  <- the design's value, verbatim
    "#bfd1f0",   # 12
)

MIDGREEN_DARK: tuple[str, ...] = (
    "#0e1310",   #  1
    "#121815",   #  2
    "#14271e",   #  3
    "#143223",   #  4
    "#1a3e2c",   #  5
    "#234b37",   #  6
    "#2c5943",   #  7
    "#336a4f",   #  8
    "#388b62",   #  9
    "#3c9669",   # 10
    "#3fbf7f",   # 11  <- the design's value, verbatim
    "#a0e2c1",   # 12
)

MIDAMBER_DARK: tuple[str, ...] = (
    "#14120d",   #  1
    "#1b1711",   #  2
    "#2a1f0d",   #  3
    "#362508",   #  4
    "#422d0a",   #  5
    "#4f3810",   #  6
    "#644c24",   #  7
    "#7f6231",   #  8
    "#e5af51",   #  9
    "#de9b26",   # 10
    "#e0a030",   # 11  <- the design's value, verbatim
    "#f4deb6",   # 12
)

MIDRED_DARK: tuple[str, ...] = (
    "#120e0e",   #  1
    "#170f10",   #  2
    "#281112",   #  3
    "#361112",   #  4
    "#421819",   #  5
    "#4e2223",   #  6
    "#612f30",   #  7
    "#7d3e40",   #  8
    "#b13135",   #  9
    "#c53237",   # 10
    "#e5484d",   # 11  <- the design's value, verbatim
    "#eb7175",   # 12
)

#: The alpha companion for MIDBLUE, DERIVED the same way as MIDNIGHT_A_DARK:
#: each step is the translucent colour that composites over the ground to
#: give that step's opaque value. The palette references {primaryA.N} for
#: selection tints and accent overlays.
MIDBLUE_A_DARK: tuple[str, ...] = (
    "#a1baff0c",   #  1
    "#a4c3ff12",   #  2
    "#5995ff2d",   #  3
    "#2d78ff40",   #  4
    "#307aff4f",   #  5
    "#5290ff62",   #  6
    "#689eff79",   #  7
    "#6aa1ff93",   #  8
    "#3a82ffc2",   #  9
    "#659dffd4",   # 10
    "#90b9ffdf",   # 11
    "#cbdeffef",   # 12
)


# ── The data hues, in Midnight's register ────────────────────────────────────
# Facet, quality, mood and notification hues are THEMEABLE, not a fixed
# vocabulary: 86 of them differ in Daylight, and Graphite defines its own. A
# palette that inherited Radix's straight would not be a palette, it would be
# Slate with a different background — which is exactly what the distinctness
# guard is for.
#
# The design does not name them, so they are not invented: each is its own
# Radix hue put through the transform the design itself defines. Mapping Radix
# blue.11 onto --accent #7FA3E1 gives lightness x0.959 and saturation x0.620 —
# a softer, cooler register — and every hue takes the same two factors. The
# hues stay themselves; the family gains one voice.
MIDCYAN_DARK: tuple[str, ...] = (
    "#0d1416",   #  1
    "#12191c",   #  2
    "#10252b",   #  3
    "#0d2e38",   #  4
    "#103944",   #  5
    "#164652",   #  6
    "#255765",   #  7
    "#2a6c7c",   #  8
    "#24859b",   #  9
    "#4194a8",   # 10
    "#60b4c5",   # 11
    "#b5dee6",   # 12
)

MIDGREEN_DARK: tuple[str, ...] = (
    "#0f1311",   #  1
    "#131816",   #  2
    "#17261f",   #  3
    "#183126",   #  4
    "#1f3d30",   #  5
    "#29493b",   #  6
    "#325846",   #  7
    "#3b6953",   #  8
    "#438867",   #  9
    "#48926e",   # 10
    "#52b686",   # 11
    "#b1e0c4",   # 12
)

MIDORANGE_DARK: tuple[str, ...] = (
    "#14110f",   #  1
    "#1a1511",   #  2
    "#2a1d12",   #  3
    "#36200d",   #  4
    "#432710",   #  5
    "#51341c",   #  6
    "#67452d",   #  7
    "#865a3e",   #  8
    "#ca6f37",   #  9
    "#d27f40",   # 10
    "#dc9d6c",   # 11
    "#f0d7bf",   # 12
)

MIDPURPLE_DARK: tuple[str, ...] = (
    "#161218",   #  1
    "#1c171f",   #  2
    "#2c2133",   #  3
    "#392943",   #  4
    "#43314f",   #  5
    "#4f3c5d",   #  6
    "#604b71",   #  7
    "#7d6294",   #  8
    "#875dab",   #  9
    "#926ab6",   # 10
    "#c8a2e9",   # 11
    "#e2d1ef",   # 12
)

MIDTEAL_DARK: tuple[str, ...] = (
    "#0e1312",   #  1
    "#121918",   #  2
    "#122524",   #  3
    "#0c2e2c",   #  4
    "#133936",   #  5
    "#1f4743",   #  6
    "#295752",   #  7
    "#306861",   #  8
    "#2c8379",   #  9
    "#2b8e81",   # 10
    "#30aa96",   # 11
    "#aeded1",   # 12
)

MIDAMBER_DARK: tuple[str, ...] = (
    "#13110d",   #  1
    "#191611",   #  2
    "#271d0f",   #  3
    "#31230b",   #  4
    "#3c2b0e",   #  5
    "#483615",   #  6
    "#5c4828",   #  7
    "#765c36",   #  8
    "#d8b157",   #  9
    "#ceb430",   # 10
    "#d1ae39",   # 11
    "#eddbb3",   # 12
)

MIDRED_DARK: tuple[str, ...] = (
    "#171212",   #  1
    "#1c1515",   #  2
    "#31191d",   #  3
    "#411a22",   #  4
    "#4f232a",   #  5
    "#5f3036",   #  6
    "#764145",   #  7
    "#995758",   #  8
    "#c45d60",   #  9
    "#cd6e6f",   # 10
    "#e79c99",   # 11
    "#f3cad1",   # 12
)

MIDBLUE_DARK: tuple[str, ...] = (
    "#10151b",   #  1
    "#141921",   #  2
    "#17273a",   #  3
    "#12304c",   #  4
    "#153b5a",   #  5
    "#25496c",   #  6
    "#365a81",   #  7
    "#416c9a",   #  8
    "#2e84c6",   #  9
    "#5697d7",   # 10
    "#7fb0e1",   # 11
    "#bfdcf0",   # 12
)


# ── Alpha companions ─────────────────────────────────────────────────────────
# DERIVED, not authored: each step is the translucent colour that composites
# over the ground to give that step's opaque value. A Radix scale ships both,
# and the loader looks up <hue>A for every {hueA.N} reference — a ramp without
# one cannot back a palette.
MIDAMBER_A_DARK: tuple[str, ...] = (
    "#ff87000a",   #  1
    "#ffa61f11",   #  2
    "#ff97081f",   #  3
    "#ff990029",   #  4
    "#ffa20635",   #  5
    "#ffb02441",   #  6
    "#ffbe5756",   #  7
    "#ffc16671",   #  8
    "#ffd064d7",   #  9
    "#ffde38cc",   # 10
    "#ffd342cf",   # 11
    "#ffebc0ec",   # 12
)

MIDCYAN_A_DARK: tuple[str, ...] = (
    "#82ffc608",   #  1
    "#b1fff00e",   #  2
    "#47e9ff1d",   #  3
    "#21d7ff2b",   #  4
    "#29dbff37",   #  5
    "#38deff46",   #  6
    "#58dfff5b",   #  7
    "#52e0ff73",   #  8
    "#37dcff94",   #  9
    "#61e2ffa2",   # 10
    "#7ceaffc1",   # 11
    "#c9f7ffe4",   # 12
)

MIDGREEN_A_DARK: tuple[str, ...] = (
    "#d9ff3307",   #  1
    "#d4ff8a0d",   #  2
    "#8cff9c1b",   #  3
    "#6cffa027",   #  4
    "#76ffaf33",   #  5
    "#88ffbb40",   #  6
    "#8cffbd50",   #  7
    "#8cffbf62",   #  8
    "#7bffba82",   #  9
    "#7bffba8d",   # 10
    "#71ffb9b2",   # 11
    "#caffdede",   # 12
)

MIDORANGE_A_DARK: tuple[str, ...] = (
    "#ff7c000b",   #  1
    "#ff8e1e12",   #  2
    "#ff8b1f22",   #  3
    "#ff79002f",   #  4
    "#ff7f103c",   #  5
    "#ff95394b",   #  6
    "#ffa15c61",   #  7
    "#ffa66b82",   #  8
    "#ff8a42c8",   #  9
    "#ff994bd0",   # 10
    "#ffb57bdb",   # 11
    "#ffe4caef",   # 12
)

MIDPURPLE_A_DARK: tuple[str, ...] = (
    "#ff7ea70d",   #  1
    "#ff9ad214",   #  2
    "#f89bff25",   #  3
    "#ea94ff36",   #  4
    "#e598ff43",   #  5
    "#e2a1ff52",   #  6
    "#dfa7ff67",   #  7
    "#dba8ff8d",   #  8
    "#cb89ffa5",   #  9
    "#ce93ffb1",   # 10
    "#dbb1ffe8",   # 11
    "#f2dfffee",   # 12
)

MIDRED_A_DARK: tuple[str, ...] = (
    "#ff75330f",   #  1
    "#ff815114",   #  2
    "#ff5c6029",   #  3
    "#ff4a5f3a",   #  4
    "#ff5d6b49",   #  5
    "#ff737d59",   #  6
    "#ff848871",   #  7
    "#ff8c8b95",   #  8
    "#ff7779c2",   #  9
    "#ff8787cb",   # 10
    "#ffaca8e6",   # 11
    "#ffd4dbf3",   # 12
)

MIDTEAL_A_DARK: tuple[str, ...] = (
    "#b7ff5507",   #  1
    "#b1ffa60e",   #  2
    "#60ffd21a",   #  3
    "#1effd824",   #  4
    "#3fffdd2f",   #  5
    "#64ffe23e",   #  6
    "#71ffe64f",   #  7
    "#70ffe661",   #  8
    "#50ffe67d",   #  9
    "#49ffe388",   # 10
    "#45ffdea6",   # 11
    "#c8ffefdc",   # 12
)


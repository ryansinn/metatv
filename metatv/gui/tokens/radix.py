"""Radix Colors scales, vendored.

Source: https://github.com/radix-ui/colors — MIT License, (c) WorkOS.
Generated from ``src/dark.ts`` / ``src/light.ts``; sRGB hex only (the
display-p3 variants are dropped, Qt stylesheets take sRGB).

Each scale is 12 steps with FIXED semantics. This is the derivation rule the
palette layer no longer has to invent per theme:

    1-2   app background          7    interactive component border
    3     component background    8    strong border / focus ring
    4     component hover         9    solid background (the "brand" step)
    5     component active       10   solid hover
    6     subtle border          11   low-contrast text
                                 12   high-contrast text

The ``_A_`` scales are those steps expressed as ALPHA over the scale's own
background. They replace MetaTV's hand-authored ``OVERLAY_*`` family, which was
39 tokens resolving to 16 base colours with hand-picked alphas.

Steps are 1-indexed in Radix's own docs and naming; ``step(SLATE_DARK, 2)``
below keeps that convention so a DTCG reference like ``{slate.2}`` maps
straight through without an off-by-one.

DO NOT hand-edit — regenerate from upstream.
"""

from __future__ import annotations


def step(scale: tuple[str, ...], n: int) -> str:
    """Return Radix step *n* (1-12) from *scale*, using Radix's own 1-indexing."""
    if not 1 <= n <= 12:
        raise ValueError(f"Radix steps are 1-12, got {n}")
    return scale[n - 1]



# ---- dark ----------------------------------------------------------

SLATE_DARK: tuple[str, ...] = (
    "#111113", "#18191b", "#212225", "#272a2d",
    "#2e3135", "#363a3f", "#43484e", "#5a6169",
    "#696e77", "#777b84", "#b0b4ba", "#edeef0",
)

SLATE_A_DARK: tuple[str, ...] = (
    "#00000000", "#d8f4f609", "#ddeaf814", "#d3edf81d",
    "#d9edfe25", "#d6ebfd30", "#d9edff40", "#d9edff5d",
    "#dfebfd6d", "#e5edfd7b", "#f1f7feb5", "#fcfdffef",
)

GRAY_DARK: tuple[str, ...] = (
    "#111111", "#191919", "#222222", "#2a2a2a",
    "#313131", "#3a3a3a", "#484848", "#606060",
    "#6e6e6e", "#7b7b7b", "#b4b4b4", "#eeeeee",
)

GRAY_A_DARK: tuple[str, ...] = (
    "#00000000", "#ffffff09", "#ffffff12", "#ffffff1b",
    "#ffffff22", "#ffffff2c", "#ffffff3b", "#ffffff55",
    "#ffffff64", "#ffffff72", "#ffffffaf", "#ffffffed",
)

SAND_DARK: tuple[str, ...] = (
    "#111110", "#191918", "#222221", "#2a2a28",
    "#31312e", "#3b3a37", "#494844", "#62605b",
    "#6f6d66", "#7c7b74", "#b5b3ad", "#eeeeec",
)

SAND_A_DARK: tuple[str, ...] = (
    "#00000000", "#f4f4f309", "#f6f6f513", "#fefef31b",
    "#fbfbeb23", "#fffaed2d", "#fffbed3c", "#fff9eb57",
    "#fffae965", "#fffdee73", "#fffcf4b0", "#fffffded",
)

BLUE_DARK: tuple[str, ...] = (
    "#0d1520", "#111927", "#0d2847", "#003362",
    "#004074", "#104d87", "#205d9e", "#2870bd",
    "#0090ff", "#3b9eff", "#70b8ff", "#c2e6ff",
)

BLUE_A_DARK: tuple[str, ...] = (
    "#004df211", "#1166fb18", "#0077ff3a", "#0075ff57",
    "#0081fd6b", "#0f89fd7f", "#2a91fe98", "#3094feb9",
    "#0090ff", "#3b9eff", "#70b8ff", "#c2e6ff",
)

INDIGO_DARK: tuple[str, ...] = (
    "#11131f", "#141726", "#182449", "#1d2e62",
    "#253974", "#304384", "#3a4f97", "#435db1",
    "#3e63dd", "#5472e4", "#9eb1ff", "#d6e1ff",
)

INDIGO_A_DARK: tuple[str, ...] = (
    "#1133ff0f", "#3354fa17", "#2f62ff3c", "#3566ff57",
    "#4171fd6b", "#5178fd7c", "#5a7fff90", "#5b81feac",
    "#4671ffdb", "#5c7efee3", "#9eb1ff", "#d6e1ff",
)

CYAN_DARK: tuple[str, ...] = (
    "#0b161a", "#101b20", "#082c36", "#003848",
    "#004558", "#045468", "#12677e", "#11809c",
    "#00a2c7", "#23afd0", "#4ccce6", "#b6ecf7",
)

CYAN_A_DARK: tuple[str, ...] = (
    "#0091f70a", "#02a7f211", "#00befd28", "#00baff3b",
    "#00befd4d", "#00c7fd5e", "#14cdff75", "#11cfff95",
    "#00cfffc3", "#28d6ffcd", "#52e1fee5", "#bbf3fef7",
)

TEAL_DARK: tuple[str, ...] = (
    "#0d1514", "#111c1b", "#0d2d2a", "#023b37",
    "#084843", "#145750", "#1c6961", "#207e73",
    "#12a594", "#0eb39e", "#0bd8b6", "#adf0dd",
)

TEAL_A_DARK: tuple[str, ...] = (
    "#00deab05", "#12fbe60c", "#00ffe61e", "#00ffe92d",
    "#00ffea3b", "#1cffe84b", "#2efde85f", "#32ffe775",
    "#13ffe49f", "#0dffe0ae", "#0afed5d6", "#b8ffebef",
)

GREEN_DARK: tuple[str, ...] = (
    "#0e1512", "#121b17", "#132d21", "#113b29",
    "#174933", "#20573e", "#28684a", "#2f7c57",
    "#30a46c", "#33b074", "#3dd68c", "#b1f1cb",
)

GREEN_A_DARK: tuple[str, ...] = (
    "#00de4505", "#29f99d0b", "#22ff991e", "#11ff992d",
    "#2bffa23c", "#44ffaa4b", "#50fdac5e", "#54ffad73",
    "#44ffa49e", "#43fea4ab", "#46fea5d4", "#bbffd7f0",
)

AMBER_DARK: tuple[str, ...] = (
    "#16120c", "#1d180f", "#302008", "#3f2700",
    "#4d3000", "#5c3d05", "#714f19", "#8f6424",
    "#ffc53d", "#ffd60a", "#ffca16", "#ffe7b3",
)

AMBER_A_DARK: tuple[str, ...] = (
    "#e63c0006", "#fd9b000d", "#fa820022", "#fc820032",
    "#fd8b0041", "#fd9b0051", "#ffab2567", "#ffae3587",
    "#ffc53d", "#ffd60a", "#ffca16", "#ffe7b3",
)

ORANGE_DARK: tuple[str, ...] = (
    "#17120e", "#1e160f", "#331e0b", "#462100",
    "#562800", "#66350c", "#7e451d", "#a35829",
    "#f76b15", "#ff801f", "#ffa057", "#ffe0c2",
)

ORANGE_A_DARK: tuple[str, ...] = (
    "#ec360007", "#fe6d000e", "#fb6a0025", "#ff590039",
    "#ff61004a", "#fd75045c", "#ff832c75", "#fe84389d",
    "#fe6d15f7", "#ff801f", "#ffa057", "#ffe0c2",
)

RED_DARK: tuple[str, ...] = (
    "#191111", "#201314", "#3b1219", "#500f1c",
    "#611623", "#72232d", "#8c333a", "#b54548",
    "#e5484d", "#ec5d5e", "#ff9592", "#ffd1d9",
)

RED_A_DARK: tuple[str, ...] = (
    "#f4121209", "#f22f3e11", "#ff173f2d", "#fe0a3b44",
    "#ff204756", "#ff3e5668", "#ff536184", "#ff5d61b0",
    "#fe4e54e4", "#ff6465eb", "#ff9592", "#ffd1d9",
)

PURPLE_DARK: tuple[str, ...] = (
    "#18111b", "#1e1523", "#301c3b", "#3d224e",
    "#48295c", "#54346b", "#664282", "#8457aa",
    "#8e4ec6", "#9a5cd0", "#d19dff", "#ecd9fa",
)

PURPLE_A_DARK: tuple[str, ...] = (
    "#b412f90b", "#b744f714", "#c150ff2d", "#bb53fd42",
    "#be5cfd51", "#c16dfd61", "#c378fd7a", "#c47effa4",
    "#b661ffc2", "#bc6fffcd", "#d19dff", "#f1ddfffa",
)

PLUM_DARK: tuple[str, ...] = (
    "#181118", "#201320", "#351a35", "#451d47",
    "#512454", "#5e3061", "#734079", "#92549c",
    "#ab4aba", "#b658c4", "#e796f3", "#f4d4f4",
)

PLUM_A_DARK: tuple[str, ...] = (
    "#f112f108", "#f22ff211", "#fd4cfd27", "#f646ff3a",
    "#f455ff48", "#f66dff56", "#f07cfd70", "#ee84ff95",
    "#e961feb6", "#ed70ffc0", "#f19cfef3", "#feddfef4",
)

PINK_DARK: tuple[str, ...] = (
    "#191117", "#21121d", "#37172f", "#4b143d",
    "#591c47", "#692955", "#833869", "#a84885",
    "#d6409f", "#de51a8", "#ff8dcc", "#fdd1ea",
)

PINK_A_DARK: tuple[str, ...] = (
    "#f412bc09", "#f420bb12", "#fe37cc29", "#fc1ec43f",
    "#fd35c24e", "#fd51c75f", "#fd62c87b", "#ff68c8a2",
    "#fe49bcd4", "#ff5cc0dc", "#ff8dcc", "#ffd3ecfd",
)

YELLOW_DARK: tuple[str, ...] = (
    "#14120b", "#1b180f", "#2d2305", "#362b00",
    "#433500", "#524202", "#665417", "#836a21",
    "#ffe629", "#ffff57", "#f5e147", "#f6eeb4",
)

YELLOW_A_DARK: tuple[str, ...] = (
    "#d1510004", "#f9b4000b", "#ffaa001e", "#fdb70028",
    "#febb0036", "#fec40046", "#fdcb225c", "#fdca327b",
    "#ffe629", "#ffff57", "#fee949f5", "#fef6baf6",
)


# ---- light ----------------------------------------------------------

SLATE_LIGHT: tuple[str, ...] = (
    "#fcfcfd", "#f9f9fb", "#f0f0f3", "#e8e8ec",
    "#e0e1e6", "#d9d9e0", "#cdced6", "#b9bbc6",
    "#8b8d98", "#80838d", "#60646c", "#1c2024",
)

SLATE_A_LIGHT: tuple[str, ...] = (
    "#00005503", "#00005506", "#0000330f", "#00002d17",
    "#0009321f", "#00002f26", "#00062e32", "#00083046",
    "#00051d74", "#00071b7f", "#0007149f", "#000509e3",
)

GRAY_LIGHT: tuple[str, ...] = (
    "#fcfcfc", "#f9f9f9", "#f0f0f0", "#e8e8e8",
    "#e0e0e0", "#d9d9d9", "#cecece", "#bbbbbb",
    "#8d8d8d", "#838383", "#646464", "#202020",
)

GRAY_A_LIGHT: tuple[str, ...] = (
    "#00000003", "#00000006", "#0000000f", "#00000017",
    "#0000001f", "#00000026", "#00000031", "#00000044",
    "#00000072", "#0000007c", "#0000009b", "#000000df",
)

SAND_LIGHT: tuple[str, ...] = (
    "#fdfdfc", "#f9f9f8", "#f1f0ef", "#e9e8e6",
    "#e2e1de", "#dad9d6", "#cfceca", "#bcbbb5",
    "#8d8d86", "#82827c", "#63635e", "#21201c",
)

SAND_A_LIGHT: tuple[str, ...] = (
    "#55550003", "#25250007", "#20100010", "#1f150019",
    "#1f180021", "#19130029", "#19140035", "#1915014a",
    "#0f0f0079", "#0c0c0083", "#080800a1", "#060500e3",
)

BLUE_LIGHT: tuple[str, ...] = (
    "#fbfdff", "#f4faff", "#e6f4fe", "#d5efff",
    "#c2e5ff", "#acd8fc", "#8ec8f6", "#5eb1ef",
    "#0090ff", "#0588f0", "#0d74ce", "#113264",
)

BLUE_A_LIGHT: tuple[str, ...] = (
    "#0080ff04", "#008cff0b", "#008ff519", "#009eff2a",
    "#0093ff3d", "#0088f653", "#0083eb71", "#0084e6a1",
    "#0090ff", "#0086f0fa", "#006dcbf2", "#002359ee",
)

INDIGO_LIGHT: tuple[str, ...] = (
    "#fdfdfe", "#f7f9ff", "#edf2fe", "#e1e9ff",
    "#d2deff", "#c1d0ff", "#abbdf9", "#8da4ef",
    "#3e63dd", "#3358d4", "#3a5bc7", "#1f2d5c",
)

INDIGO_A_LIGHT: tuple[str, ...] = (
    "#00008002", "#0040ff08", "#0047f112", "#0044ff1e",
    "#0044ff2d", "#003eff3e", "#0037ed54", "#0034dc72",
    "#0031d2c1", "#002ec9cc", "#002bb7c5", "#001046e0",
)

CYAN_LIGHT: tuple[str, ...] = (
    "#fafdfe", "#f2fafb", "#def7f9", "#caf1f6",
    "#b5e9f0", "#9ddde7", "#7dcedc", "#3db9cf",
    "#00a2c7", "#0797b9", "#107d98", "#0d3c48",
)

CYAN_A_LIGHT: tuple[str, ...] = (
    "#0099cc05", "#009db10d", "#00c2d121", "#00bcd435",
    "#01b4cc4a", "#00a7c162", "#009fbb82", "#00a3c0c2",
    "#00a2c7", "#0094b7f8", "#007491ef", "#00323ef2",
)

TEAL_LIGHT: tuple[str, ...] = (
    "#fafefd", "#f3fbf9", "#e0f8f3", "#ccf3ea",
    "#b8eae0", "#a1ded2", "#83cdc1", "#53b9ab",
    "#12a594", "#0d9b8a", "#008573", "#0d3d38",
)

TEAL_A_LIGHT: tuple[str, ...] = (
    "#00cc9905", "#00aa800c", "#00c69d1f", "#00c39633",
    "#00b49047", "#00a6855e", "#0099807c", "#009783ac",
    "#009e8ced", "#009684f2", "#008573", "#00332df2",
)

GREEN_LIGHT: tuple[str, ...] = (
    "#fbfefc", "#f4fbf6", "#e6f6eb", "#d6f1df",
    "#c4e8d1", "#adddc0", "#8eceaa", "#5bb98b",
    "#30a46c", "#2b9a66", "#218358", "#193b2d",
)

GREEN_A_LIGHT: tuple[str, ...] = (
    "#00c04004", "#00a32f0b", "#00a43319", "#00a83829",
    "#019c393b", "#00963c52", "#00914071", "#00924ba4",
    "#008f4acf", "#008647d4", "#00713fde", "#002616e6",
)

AMBER_LIGHT: tuple[str, ...] = (
    "#fefdfb", "#fefbe9", "#fff7c2", "#ffee9c",
    "#fbe577", "#f3d673", "#e9c162", "#e2a336",
    "#ffc53d", "#ffba18", "#ab6400", "#4f3422",
)

AMBER_A_LIGHT: tuple[str, ...] = (
    "#c0800004", "#f4d10016", "#ffde003d", "#ffd40063",
    "#f8cf0088", "#eab5008c", "#dc9b009d", "#da8a00c9",
    "#ffb300c2", "#ffb300e7", "#ab6400", "#341500dd",
)

ORANGE_LIGHT: tuple[str, ...] = (
    "#fefcfb", "#fff7ed", "#ffefd6", "#ffdfb5",
    "#ffd19a", "#ffc182", "#f5ae73", "#ec9455",
    "#f76b15", "#ef5f00", "#cc4e00", "#582d1d",
)

ORANGE_A_LIGHT: tuple[str, ...] = (
    "#c0400004", "#ff8e0012", "#ff9c0029", "#ff91014a",
    "#ff8b0065", "#ff81007d", "#ed6c008c", "#e35f00aa",
    "#f65e00ea", "#ef5f00", "#cc4e00", "#431200e2",
)

RED_LIGHT: tuple[str, ...] = (
    "#fffcfc", "#fff7f7", "#feebec", "#ffdbdc",
    "#ffcdce", "#fdbdbe", "#f4a9aa", "#eb8e90",
    "#e5484d", "#dc3e42", "#ce2c31", "#641723",
)

RED_A_LIGHT: tuple[str, ...] = (
    "#ff000003", "#ff000008", "#f3000d14", "#ff000824",
    "#ff000632", "#f8000442", "#df000356", "#d2000571",
    "#db0007b7", "#d10005c1", "#c40006d3", "#55000de8",
)

PURPLE_LIGHT: tuple[str, ...] = (
    "#fefcfe", "#fbf7fe", "#f7edfe", "#f2e2fc",
    "#ead5f9", "#e0c4f4", "#d1afec", "#be93e4",
    "#8e4ec6", "#8347b9", "#8145b5", "#402060",
)

PURPLE_A_LIGHT: tuple[str, ...] = (
    "#aa00aa03", "#8000e008", "#8e00f112", "#8d00e51d",
    "#8000db2a", "#7a01d03b", "#6d00c350", "#6600c06c",
    "#5c00adb1", "#53009eb8", "#52009aba", "#250049df",
)

PLUM_LIGHT: tuple[str, ...] = (
    "#fefcff", "#fdf7fd", "#fbebfb", "#f7def8",
    "#f2d1f3", "#e9c2ec", "#deade3", "#cf91d8",
    "#ab4aba", "#a144af", "#953ea3", "#53195d",
)

PLUM_A_LIGHT: tuple[str, ...] = (
    "#aa00ff03", "#c000c008", "#cc00cc14", "#c200c921",
    "#b700bd2e", "#a400b03d", "#9900a852", "#9000a56e",
    "#89009eb5", "#7f0092bb", "#730086c1", "#40004be6",
)

PINK_LIGHT: tuple[str, ...] = (
    "#fffcfe", "#fef7fb", "#fee9f5", "#fbdcef",
    "#f6cee7", "#efbfdd", "#e7acd0", "#dd93c2",
    "#d6409f", "#cf3897", "#c2298a", "#651249",
)

PINK_A_LIGHT: tuple[str, ...] = (
    "#ff00aa03", "#e0008008", "#f4008c16", "#e2008b23",
    "#d1008331", "#c0007840", "#b6006f53", "#af006f6c",
    "#c8007fbf", "#c2007ac7", "#b60074d6", "#59003bed",
)

YELLOW_LIGHT: tuple[str, ...] = (
    "#fdfdf9", "#fefce9", "#fffab8", "#fff394",
    "#ffe770", "#f3d768", "#e4c767", "#d5ae39",
    "#ffe629", "#ffdc00", "#9e6c00", "#473b1f",
)

YELLOW_A_LIGHT: tuple[str, ...] = (
    "#aaaa0006", "#f4dd0016", "#ffee0047", "#ffe3016b",
    "#ffd5008f", "#ebbc0097", "#d2a10098", "#c99700c6",
    "#ffe100d6", "#ffdc00", "#9e6c00", "#2e2000e0",
)

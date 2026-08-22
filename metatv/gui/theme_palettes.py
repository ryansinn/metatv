"""Named colour/typography palettes for theme.py.

Pure data — no Qt import, no derived/composed values.  Each palette is a flat
dict of token name -> literal value (str, or list[str] for BACKDROP_TINTS).
``theme.py`` owns rebinding these into its module-level ``COLOR_*``/``FONT_*``/
``OVERLAY_*`` names (the design-token layer) and recomposing every semantic
constant from them; this module is the only OTHER place those literals may
live, alongside theme.py's own handful of token-to-token DERIVED assignments
(e.g. ``COLOR_LINK = COLOR_ACCENT_BLUE``) that aren't stored here because
their value is just "whatever the source token currently is", not an
independent per-palette choice.

Every palette defines exactly the same key set — token NAMES are the one
stable public surface; only VALUES vary by palette (enforced by
tests/test_theme_palettes.py AND tests/test_palette_completeness.py,
parametrized over ``PALETTES``). Each palette also declares its ``kind``
("light"/"dark") in :data:`PALETTE_KIND` below — that declaration is what
lets test_palette_completeness.py assert every background/surface token is
actually dark-in-a-dark-palette / light-in-a-light-one, the single check
that would have caught this file's original wave7/theme-system bug: Graphite
shipped 96% byte-identical to Midnight (6 of 152 tokens touched) and
Daylight shipped 80% identical with 13 of its 23 background/surface tokens
still dark (including the "Global Exclusions" banner, which rendered as a
dark-olive bar on a light theme). See #251 for the fix.

Design notes on what varies vs. what's held fixed across all three palettes:

* **Midnight** is the shipped default, values copied verbatim from the
  pre-theme-system constants — pixel-identical to today, by construction.
* **Graphite** is a genuinely distinct neutral dark variant, not a reskin:
  the whole structural surface ramp (border/hairline/bar/section/card
  backgrounds) AND the text ramp shift to a flatter, distinctly LIGHTER,
  fully neutral (R=G=B, no blue cast) grey than Midnight's near-black, with
  wider gaps between elevation steps than Midnight's own (its own ramp, not
  Midnight's shifted uniformly) — plus a small, hue-preserving
  lighten+desaturate pass over the remaining decorative/link tokens so the
  two dark palettes are visually and numerically distinct (see
  ``test_palettes_are_mutually_distinct``) while staying unmistakably "the
  same app, a different dark theme."
* **Daylight** is a genuine light theme: the text ramp, structural surfaces,
  status colors (OK/WARN/ERR), notify/banner/recipe fills, and the generic
  hover/press overlays (OVERLAY_03..18, which FLIP from a white-tint to a
  black-based tint — a "lighten on hover" trick that reads as subtle
  feedback on a dark surface would either do nothing or overshoot to pure
  white on a light one) all get real light-theme values. Solid accent/link/
  facet colours that read as TEXT against app chrome (ACCENT_*, FACET_*,
  GOLD_LIGHT, PREF_NUDGE, ERR_MUTED) are darkened to keep >= 4.5:1 contrast
  against the new light backgrounds, hue preserved throughout — a colour
  that only "passes a luminance threshold" without staying legible/
  recognisable is exactly the failure mode this rewrite is guarding against,
  not just the letter of the test.
* **Held theme-invariant on purpose, in every palette** (same literal value
  in all three — each individually justified, not a blanket "brand colours
  never change" rule, since e.g. COLOR_NOTIFY_*_BG and the mood chips
  described below turned out to need per-palette treatment despite an
  earlier draft of this docstring claiming otherwise): FONT_* (a type scale,
  not a colour concern); the "frosted-light" OVERLAY_40/55 pair and
  COLOR_ACCENT_BLUE_LIGHT, which sit over POSTER IMAGES (photographic, never
  reskinned) rather than app chrome; the filled-chip family that pairs a
  saturated fill with a fixed white/self-contained foreground regardless of
  app theme (COLOR_QUALITY_UHD/FHD/HD/RAW/LIVE — the owner explicitly likes
  this hue system and it must stay mutually distinguishable, so this slice
  left it untouched rather than risk collapsing two hues together;
  COLOR_AUDIO_BADGE, COLOR_BTN_SAVE(_HOVER), COLOR_PPV_ACCENT, COLOR_GOLD);
  and COLOR_RED_BRIGHT/COLOR_ACCENT_BLUE_2, which the mood-chip family below
  depends on staying fixed.
* **Mood chips** (COLOR_MOOD_LIKE/CURIOUS/NOTFORME/DISLIKE/TRASH/WATCH/
  EXPLORE, category_picker_dialog.py) are self-contained FILLED badges — each
  pairs its own saturated fill with either a dedicated per-palette
  foreground already tuned for that exact fill, or a foreground (themed
  COLOR_TEXT_HI, or the invariant COLOR_RED_BRIGHT/COLOR_ACCENT_BLUE_2 brand
  accents) that already stays legible against it unmodified. Like a coloured
  status pill in most design systems, they're meant to stay recognisable
  regardless of the app shell's overall darkness, not track it — confirmed
  empirically while building test_palette_completeness.py: even MIDNIGHT
  (the blessed, "pixel-identical to today" baseline) fails a blanket
  <0.35-luminance-for-dark rule on four of these fills, proving the rule is
  too strict for this family rather than the values being a bug. All seven
  stay byte-identical across every palette.
* **The Similar-Titles lightbox / Explore trail-map family** (theme.py's
  "Similar-titles lightbox (redesign)" + "Explore trail-map" sections) is a
  deliberately fixed dark "cinema" backdrop in every palette — like a modal
  photo viewer that stays dark regardless of OS/app theme. Its own background
  tokens (COLOR_LIGHTBOX_BG/COLOR_LIGHTBOX_HEADER, COLOR_BG_DEEP) are
  theme-invariant — COLOR_BG_DEEP additionally does double duty as a fixed
  DARK TEXT colour on badges that always have a bright/coloured fill
  (theme.py QUEUE_MATCHED_NEW_TAG, TRAILMAP_HERE_TAG), so lightening it for
  Daylight would make that badge text illegible on top of breaking the
  cinema backdrop. This file adds two dedicated, ALSO invariant, text tokens
  (COLOR_LIGHTBOX_TEXT_HI/COLOR_LIGHTBOX_TEXT) that theme.py's semantic layer
  uses in place of the (now themed) generic COLOR_TEXT_HI/COLOR_TEXT ramp —
  otherwise Daylight's near-black text ramp would render illegibly on that
  family's fixed-dark background. KNOWN, ACCEPTED COMPROMISE: a few
  lower-severity reads inside that same family (COLOR_MUTED/COLOR_FAINT/
  COLOR_DIM for secondary text, OVERLAY_03/05 for row hover) still read from
  the generic (themed) tokens — in Daylight these stay in a mid-grey band
  that's legible-but-flatter on a dark background rather than fully
  invisible, and hover feedback there gets subtler rather than vanishing.
  Giving that family a fully independent fixed sub-palette is a reasonable
  follow-up if it reads as a real UX papercut in practice.
* **COLOR_ON_ACCENT** is the foreground for anything drawn ON a solid
  COLOR_ACCENT fill — the QPalette selection highlight above all. It is a
  SEPARATE token from COLOR_TEXT_HI because the two answer different
  questions: COLOR_TEXT_HI is "brightest text on the app background",
  COLOR_ON_ACCENT is "legible text on the accent". In the dark palettes they
  coincide, which is exactly what hid the bug — Daylight is a light theme
  whose text ramp runs to near-black (#0d0d0d) while its accent stays a dark
  navy (#073256), so reusing the ramp gave selected rows ~1.2:1 and made the
  selection unreadable. Anywhere COLOR_ACCENT is a background, the foreground
  is COLOR_ON_ACCENT, never the text ramp.
* **COLOR_SURFACE_LIGHT/_2/_3** are the inverse case of the lightbox family
  above: a fixed-LIGHT "highlight chip" surface used by filter_bar.py /
  sports_filter_bar.py regardless of app theme, always light in every
  palette by design.
* **COLOR_ACCENT_ORANGE_FADED** is the one 8-digit ``#RRGGBBAA`` value in
  this file; it stayed byte-identical across all three palettes before this
  slice and stays that way now (re-deriving the alpha-baked format correctly
  was out of scope here — low-traffic decorative use, filter_group_row.py's
  "— filter" and-axis label).
"""

from __future__ import annotations

from pathlib import Path as _Path

TokenValue = str | list[str]


_MIDNIGHT_LEGACY: dict[str, TokenValue] = {
    'COLOR_TEXT_HI': '#fff',
    'COLOR_TEXT': '#ccc',
    'COLOR_TEXT_2': '#ddd',
    'COLOR_TEXT_LOW': '#bbb',
    'COLOR_DIM': '#aaa',
    'COLOR_DIM_2': '#999',
    'COLOR_MUTED': '#888',
    'COLOR_DISABLED': '#777',
    'COLOR_MUTED_2': '#666',
    'COLOR_FAINT': '#555',
    'COLOR_GRAY': 'gray',
    'COLOR_LIGHTGRAY': 'lightgray',
    'COLOR_BORDER': '#444',
    'COLOR_LINE': '#333',
    'COLOR_LINE_DARK': '#2a2a2a',
    'COLOR_BG_BAR': '#1e1e1e',
    'COLOR_BG_SECTION': '#1a1a1a',
    'COLOR_ACCENT': '#2288dd',
    'COLOR_ACCENT_HOVER': '#55aaff',
    # Dark, not white: #2288dd is a LIGHT blue, so white on it is 2.09:1 —
    # the conventional dark-theme look, but genuinely hard to read. Near-black
    # gets 4.97:1 on the same fill without touching the accent itself (which
    # doubles as a foreground/border token and must stay light here).
    'COLOR_ON_ACCENT': '#0d0d0d',
    'COLOR_OK': '#4CAF50',
    'COLOR_WARN': '#FFC107',
    'COLOR_ERR': '#F44336',
    'COLOR_ERR_2': '#e05050',
    'COLOR_GOLD': 'gold',
    'COLOR_ACCENT_BLUE': '#4488ff',
    'COLOR_ACCENT_BLUE_2': '#88aaff',
    'COLOR_ACCENT_BLUE_3': '#99bbff',
    'COLOR_ACCENT_GREEN': '#44aa77',
    'COLOR_ACCENT_PURPLE': '#9966cc',
    'COLOR_ACCENT_ORANGE': '#f0a040',
    'COLOR_ACCENT_ORANGE_FADED': '#f0a04077',
    'COLOR_ACCENT_TEAL': '#33bb88',
    'COLOR_ACCENT_BROWN': '#cc7722',
    'COLOR_BTN_SAVE': '#2255cc',
    'COLOR_BTN_SAVE_HOVER': '#3366dd',
    'COLOR_EXCLUSIONS_ACTIVE': '#2a9d8f',
    'OVERLAY_ORANGE_12': 'rgba(240,160,64,0.12)',
    'OVERLAY_EXCLUSIONS_10': 'rgba(42,157,143,0.10)',
    'OVERLAY_EXCLUSIONS_18': 'rgba(42,157,143,0.18)',
    'OVERLAY_ORANGE_10': 'rgba(240,160,64,0.10)',
    'OVERLAY_ORANGE_18': 'rgba(240,160,64,0.18)',
    'OVERLAY_03': 'rgba(255,255,255,0.03)',
    'OVERLAY_04': 'rgba(255,255,255,0.04)',
    'OVERLAY_05': 'rgba(255,255,255,0.05)',
    'OVERLAY_08': 'rgba(255,255,255,0.08)',
    'OVERLAY_10': 'rgba(255,255,255,0.10)',
    'OVERLAY_15': 'rgba(255,255,255,0.15)',
    'OVERLAY_18': 'rgba(255,255,255,0.18)',
    'OVERLAY_40': 'rgba(255,255,255,0.40)',
    'OVERLAY_55': 'rgba(255,255,255,0.55)',
    'OVERLAY_ACCENT_35': 'rgba(34,136,221,0.35)',
    'OVERLAY_ACCENT_50': 'rgba(34,136,221,0.50)',
    'OVERLAY_POPUP': 'rgba(40,40,50,0.97)',
    'OVERLAY_BLUE_10': 'rgba(68,136,255,0.1)',
    'OVERLAY_BLUE_15': 'rgba(68,136,255,0.15)',
    'OVERLAY_BLUE_20': 'rgba(68,136,255,0.2)',
    'OVERLAY_BLUE_25': 'rgba(68,136,255,0.25)',
    'OVERLAY_BLUE_40': 'rgba(68,136,255,0.4)',
    'OVERLAY_BLUE_60': 'rgba(68,136,255,0.6)',
    'OVERLAY_ERR': 'rgba(224,80,80,0.2)',
    'OVERLAY_ERR_15': 'rgba(224,80,80,0.15)',
    'OVERLAY_PLATFORM_BADGE': 'rgba(60,120,180,0.5)',
    'COLOR_QUALITY_UHD': '#7755cc',
    'COLOR_QUALITY_FHD': '#3388dd',
    'COLOR_QUALITY_HD': '#229977',
    'COLOR_QUALITY_RAW': '#cc8822',
    'COLOR_QUALITY_LIVE': '#bb9900',
    # Outline-chip variants (#257) — same hue as the COLOR_QUALITY_* solid-fill
    # family above, lightness tuned so text/border on the channel-list's own
    # OUTLINE quality chip clears a 4.5:1 contrast floor against
    # COLOR_BG_SECTION (verified >=5.0:1 here) — see badge_utils.
    # _quality_outline_colors and test_palette_completeness.py's
    # test_quality_outline_chip_contrast_at_least_4_5_every_palette.
    'COLOR_QUALITY_OUTLINE_UHD': '#baa9e5',
    'COLOR_QUALITY_OUTLINE_FHD': '#8fbeec',
    'COLOR_QUALITY_OUTLINE_HD': '#65ddbb',
    'COLOR_QUALITY_OUTLINE_RAW': '#e4ae5d',
    'COLOR_QUALITY_OUTLINE_LIVE': '#e8be00',
    'COLOR_AUDIO_BADGE': '#556633',
    'COLOR_MOOD_LIKE_BG': '#2ecc71',
    'COLOR_MOOD_LIKE_FG': '#1a7a43',
    'COLOR_MOOD_CURIOUS_BG': '#27ae60',
    'COLOR_MOOD_CURIOUS_FG': '#155a2e',
    'COLOR_MOOD_NOTFORME_BG': '#c0392b',
    'COLOR_MOOD_NOTFORME_FG': '#f5a5a0',
    'COLOR_MOOD_DISLIKE_BG': '#e74c3c',
    'COLOR_MOOD_TRASH_BG': '#5a1a1a',
    'COLOR_MOOD_WATCH_BG': '#1a3a5a',
    'COLOR_MOOD_EXPLORE_BG': '#1a3a1a',
    'COLOR_MOOD_EXPLORE_FG': '#88cc88',
    'COLOR_NOTIFY_ERR_BG': '#2c1515',
    'COLOR_NOTIFY_ERR_BORDER': '#ff4444',
    'COLOR_NOTIFY_OK_BG': '#152c15',
    'COLOR_NOTIFY_OK_BORDER': '#44ff44',
    'COLOR_NOTIFY_WARN_BG': '#2c2415',
    'COLOR_NOTIFY_WARN_BORDER': '#ffaa44',
    'COLOR_NOTIFY_INFO_BG': '#1a1a2e',
    'COLOR_LIGHTBOX_BG': '#1e1e2e',
    'COLOR_LIGHTBOX_HEADER': '#2a2a3e',
    'COLOR_BANNER_YEL_BG': '#3a3a1a',
    'COLOR_BANNER_YEL_FG': '#e8d44d',
    'COLOR_BANNER_YEL_BORDER': '#7a7a30',
    'COLOR_BANNER_YEL_BG_HOVER': '#4a4a22',
    'COLOR_BANNER_YEL_BORDER_HOVER': '#aaaa50',
    'COLOR_PPV_ACCENT': '#ff6b35',
    'COLOR_FACET_GENRE': '#7bd88f',
    'COLOR_FACET_LANGUAGE': '#34d3c0',
    'COLOR_FACET_SUBTITLE': '#5bc4b0',
    'COLOR_FACET_DUB': '#4db8e8',
    'COLOR_FACET_FORMAT': '#c8a96e',
    'COLOR_FACET_REGION': '#f5b73d',
    'COLOR_FACET_PLATFORM': '#a78bfa',
    'COLOR_FACET_DECADE': '#6ea8ff',
    'COLOR_FACET_QUALITY': '#9fb9d4',
    'COLOR_FACET_COLLECTION': '#ef7faa',
    'COLOR_RECIPE_BG': '#07080b',
    'COLOR_RECIPE_PANEL_BG': '#0a0d12',
    'COLOR_RECIPE_TEXT': '#edeae0',
    'COLOR_RECIPE_MUTED': '#9aa0ad',
    'COLOR_RECIPE_MUTED_2': '#5b626f',
    'OVERLAY_RECIPE_SELECTED': 'rgba(245,183,61,0.08)',
    'OVERLAY_SELECTION': 'rgba(68,136,255,0.16)',
    'COLOR_RED_BRIGHT': '#ff8888',
    'COLOR_ERR_MUTED': '#aa6666',
    'COLOR_GOLD_LIGHT': '#ffe566',
    'COLOR_PREF_NUDGE': '#8fca8f',
    'COLOR_ACCENT_BLUE_LIGHT': '#aad4ff',
    'COLOR_BG_CARD': '#252525',
    'COLOR_BG_DEEP': '#111111',
    'COLOR_SURFACE_LIGHT': '#f5f5f5',
    'COLOR_SURFACE_LIGHT_2': '#e0e0e0',
    'COLOR_SURFACE_LIGHT_3': '#d0d0d0',
    'BACKDROP_TINTS': ['#1a3a5c', '#2d4a1e', '#4a1e2d', '#2d1e4a', '#1e4a3a', '#3a2d1e'],
    'OVERLAY_BROWN_08': 'rgba(204,136,0,0.08)',
    'OVERLAY_GREEN_15': 'rgba(80,160,80,0.15)',
    'OVERLAY_GREEN_40': 'rgba(80,160,80,0.4)',
    'OVERLAY_TEAL_15': 'rgba(51,187,136,0.15)',
    'OVERLAY_ERR2_15': 'rgba(204,68,68,0.15)',
    'OVERLAY_WARN_06': 'rgba(255,200,0,0.06)',
    'OVERLAY_BLACK_30': 'rgba(0,0,0,0.3)',
    'OVERLAY_BLACK_55': 'rgba(0,0,0,0.55)',
    'OVERLAY_BLACK_60': 'rgba(0,0,0,0.6)',
    'OVERLAY_BLACK_65': 'rgba(0,0,0,0.65)',
    'OVERLAY_BLUE_LT_25': 'rgba(136,170,255,0.25)',
    'FONT_XS': '9px',
    'FONT_SM': '10px',
    'FONT_MD': '11px',
    'FONT_LG': '12px',
    'FONT_XL': '13px',
    'FONT_2XL': '14px',
    'FONT_3XL': '18px',
    'FONT_4XL': '20px',
    'FONT_HEADING': '15px',
    'FONT_INPUT': '16px',
    'FONT_ICON': '17px',
    'FONT_ICON_LG': '24px',
    'FONT_CLOUD_1': '11px',
    'FONT_CLOUD_2': '13px',
    'FONT_CLOUD_3': '15px',
    'FONT_CLOUD_4': '18px',
    'FONT_CLOUD_5': '22px',
    'FONT_CLOUD_6': '27px',
    'COLOR_LIGHTBOX_TEXT_HI': '#ffffff',
    'COLOR_LIGHTBOX_TEXT': '#cccccc',
    # ── The rest of the fixed "cinema" family ────────────────────────────────
    # IDENTICAL in all three palettes ON PURPOSE, exactly like the four tokens
    # above. The preview overlay is a deliberately fixed-dark surface in EVERY
    # theme, so a foreground painted on it cannot come from a palette-tuned
    # token: Daylight's are chosen for a LIGHT app background, and measured
    # against the card they collapse — the Back button landed at 1.06:1
    # (invisible), the keyboard-hint chips and poster wells rendered as WHITE
    # boxes on the dark card, and the state glyphs at 1.24:1.
    # Any new role that paints on COLOR_LIGHTBOX_BG/_HEADER takes its colour
    # from this family; tests/test_lightbox_surface_contrast.py measures every
    # one of them against the surface it actually lands on.
    # NOT yet extended to the TRAILMAP_* family: the Explore trail-map mixes
    # this dark shell with genuine app-surface regions, so which surface each
    # of its roles lands on is a real per-role question — its own pass.
    'COLOR_LIGHTBOX_LINK': '#aad4ff',
    'COLOR_LIGHTBOX_MUTED': '#9aa0ab',
    'COLOR_LIGHTBOX_FAINT': '#8f96a1',
    'COLOR_LIGHTBOX_SUNKEN': '#15151f',
    'COLOR_LIGHTBOX_LINE': '#3a3a4e',
    'COLOR_LIGHTBOX_BORDER': '#43435a',
    'COLOR_LIGHTBOX_ACCENT': '#6cb6ff',
    'COLOR_LIGHTBOX_FILL': '#1f6fc7',
    'COLOR_LIGHTBOX_FILL_HOVER': '#2f7fd6',
    'COLOR_LIGHTBOX_ON_FILL': '#ffffff',
    'COLOR_LIGHTBOX_GOLD': '#ffc857',
    'COLOR_LIGHTBOX_OK': '#5fd08a',
}


_GRAPHITE_LEGACY: dict[str, TokenValue] = {
    'COLOR_TEXT_HI': '#f2f2f2',
    'COLOR_TEXT': '#c9c9c9',
    'COLOR_TEXT_2': '#dcdcdc',
    'COLOR_TEXT_LOW': '#b6b6b6',
    'COLOR_DIM': '#a3a3a3',
    'COLOR_DIM_2': '#929292',
    'COLOR_MUTED': '#7f7f7f',
    'COLOR_DISABLED': '#6e6e6e',
    'COLOR_MUTED_2': '#5d5d5d',
    'COLOR_FAINT': '#4c4c4c',
    'COLOR_GRAY': '#8a8a8a',
    'COLOR_LIGHTGRAY': '#cfcfcf',
    'COLOR_BORDER': '#5e5e5e',
    'COLOR_LINE': '#484848',
    'COLOR_LINE_DARK': '#272727',
    'COLOR_BG_BAR': '#2e2e2e',
    'COLOR_BG_SECTION': '#1f1f1f',
    'COLOR_ACCENT': '#3c8fd5',
    'COLOR_ACCENT_HOVER': '#70b3f6',
    'COLOR_ON_ACCENT': '#0f0f0f',   # 5.01:1 on #3c8fd5; white would be 1.93:1
    'COLOR_OK': '#5db060',
    'COLOR_WARN': '#f1bf27',
    'COLOR_ERR': '#ea5c51',
    'COLOR_ERR_2': '#db6767',
    'COLOR_GOLD': 'gold',
    'COLOR_ACCENT_BLUE': '#6096f5',
    'COLOR_ACCENT_BLUE_2': '#88aaff',
    'COLOR_ACCENT_BLUE_3': '#b0c9fa',
    'COLOR_ACCENT_GREEN': '#50b080',
    'COLOR_ACCENT_PURPLE': '#a279cb',
    'COLOR_ACCENT_ORANGE': '#e8a75a',
    'COLOR_ACCENT_ORANGE_FADED': '#f0a04077',
    'COLOR_ACCENT_TEAL': '#40c090',
    'COLOR_ACCENT_BROWN': '#d08030',
    'COLOR_BTN_SAVE': '#2255cc',
    'COLOR_BTN_SAVE_HOVER': '#3366dd',
    'COLOR_EXCLUSIONS_ACTIVE': '#35a496',
    'OVERLAY_ORANGE_12': 'rgba(232,167,90,0.14)',
    'OVERLAY_EXCLUSIONS_10': 'rgba(53,164,150,0.12)',
    'OVERLAY_EXCLUSIONS_18': 'rgba(53,164,150,0.2)',
    'OVERLAY_ORANGE_10': 'rgba(232,167,90,0.12)',
    'OVERLAY_ORANGE_18': 'rgba(232,167,90,0.2)',
    'OVERLAY_03': 'rgba(255,255,255,0.05)',
    'OVERLAY_04': 'rgba(255,255,255,0.06)',
    'OVERLAY_05': 'rgba(255,255,255,0.07)',
    'OVERLAY_08': 'rgba(255,255,255,0.1)',
    'OVERLAY_10': 'rgba(255,255,255,0.12)',
    'OVERLAY_15': 'rgba(255,255,255,0.17)',
    'OVERLAY_18': 'rgba(255,255,255,0.2)',
    'OVERLAY_40': 'rgba(255,255,255,0.42)',
    'OVERLAY_55': 'rgba(255,255,255,0.57)',
    'OVERLAY_ACCENT_35': 'rgba(60,143,213,0.37)',
    'OVERLAY_ACCENT_50': 'rgba(60,143,213,0.52)',
    'OVERLAY_POPUP': 'rgba(49,49,59,0.99)',
    'OVERLAY_BLUE_10': 'rgba(96,150,245,0.12)',
    'OVERLAY_BLUE_15': 'rgba(96,150,245,0.17)',
    'OVERLAY_BLUE_20': 'rgba(96,150,245,0.22)',
    'OVERLAY_BLUE_25': 'rgba(96,150,245,0.27)',
    'OVERLAY_BLUE_40': 'rgba(96,150,245,0.42)',
    'OVERLAY_BLUE_60': 'rgba(96,150,245,0.62)',
    'OVERLAY_ERR': 'rgba(219,103,103,0.22)',
    'OVERLAY_ERR_15': 'rgba(219,103,103,0.17)',
    'OVERLAY_PLATFORM_BADGE': 'rgba(73,129,184,0.52)',
    'COLOR_QUALITY_UHD': '#7755cc',
    'COLOR_QUALITY_FHD': '#3388dd',
    'COLOR_QUALITY_HD': '#229977',
    'COLOR_QUALITY_RAW': '#cc8822',
    'COLOR_QUALITY_LIVE': '#bb9900',
    # Outline-chip variants (#257) — see the Midnight block above for the
    # full rationale comment (identical across all three palettes).
    'COLOR_QUALITY_OUTLINE_UHD': '#d1c6ee',
    'COLOR_QUALITY_OUTLINE_FHD': '#b5d4f3',
    'COLOR_QUALITY_OUTLINE_HD': '#99e8d2',
    'COLOR_QUALITY_OUTLINE_RAW': '#edc994',
    'COLOR_QUALITY_OUTLINE_LIVE': '#ffd721',
    'COLOR_AUDIO_BADGE': '#556633',
    'COLOR_MOOD_LIKE_BG': '#2ecc71',
    'COLOR_MOOD_LIKE_FG': '#1a7a43',
    'COLOR_MOOD_CURIOUS_BG': '#27ae60',
    'COLOR_MOOD_CURIOUS_FG': '#155a2e',
    'COLOR_MOOD_NOTFORME_BG': '#c0392b',
    'COLOR_MOOD_NOTFORME_FG': '#f5a5a0',
    'COLOR_MOOD_DISLIKE_BG': '#e74c3c',
    'COLOR_MOOD_TRASH_BG': '#5a1a1a',
    'COLOR_MOOD_WATCH_BG': '#1a3a5a',
    'COLOR_MOOD_EXPLORE_BG': '#1a3a1a',
    'COLOR_MOOD_EXPLORE_FG': '#88cc88',
    'COLOR_NOTIFY_ERR_BG': '#361d1d',
    'COLOR_NOTIFY_ERR_BORDER': '#f56060',
    'COLOR_NOTIFY_OK_BG': '#1d361d',
    'COLOR_NOTIFY_OK_BORDER': '#60f560',
    'COLOR_NOTIFY_WARN_BG': '#362d1d',
    'COLOR_NOTIFY_WARN_BORDER': '#f5b160',
    'COLOR_NOTIFY_INFO_BG': '#222238',
    'COLOR_LIGHTBOX_BG': '#1e1e2e',
    'COLOR_LIGHTBOX_HEADER': '#2a2a3e',
    'COLOR_BANNER_YEL_BG': '#444422',
    'COLOR_BANNER_YEL_FG': '#e2d265',
    'COLOR_BANNER_YEL_BORDER': '#82823a',
    'COLOR_BANNER_YEL_BG_HOVER': '#53532a',
    'COLOR_BANNER_YEL_BORDER_HOVER': '#acac60',
    'COLOR_PPV_ACCENT': '#ff6b35',
    'COLOR_FACET_GENRE': '#8ed79e',
    'COLOR_FACET_LANGUAGE': '#4ccdbe',
    'COLOR_FACET_SUBTITLE': '#6ec3b3',
    'COLOR_FACET_DUB': '#65bbe2',
    'COLOR_FACET_FORMAT': '#c8af80',
    'COLOR_FACET_REGION': '#ecba58',
    'COLOR_FACET_PLATFORM': '#b7a2f5',
    'COLOR_FACET_DECADE': '#87b4f7',
    'COLOR_FACET_QUALITY': '#aec2d7',
    'COLOR_FACET_COLLECTION': '#eb95b6',
    'COLOR_RECIPE_BG': '#0e1015',
    'COLOR_RECIPE_PANEL_BG': '#11151d',
    'COLOR_RECIPE_TEXT': '#f3f1ec',
    'COLOR_RECIPE_MUTED': '#a5aab4',
    'COLOR_RECIPE_MUTED_2': '#646b78',
    'OVERLAY_RECIPE_SELECTED': 'rgba(236,186,88,0.1)',
    'OVERLAY_SELECTION': 'rgba(96,150,245,0.18)',
    'COLOR_RED_BRIGHT': '#ff8888',
    'COLOR_ERR_MUTED': '#ad7575',
    'COLOR_GOLD_LIGHT': '#f7e380',
    'COLOR_PREF_NUDGE': '#9ecd9e',
    'COLOR_ACCENT_BLUE_LIGHT': '#aad4ff',
    'COLOR_BG_CARD': '#3c3c3c',
    'COLOR_BG_DEEP': '#111111',
    'COLOR_SURFACE_LIGHT': '#f5f5f5',
    'COLOR_SURFACE_LIGHT_2': '#e0e0e0',
    'COLOR_SURFACE_LIGHT_3': '#d0d0d0',
    'BACKDROP_TINTS': ['#1a3a5c', '#2d4a1e', '#4a1e2d', '#2d1e4a', '#1e4a3a', '#3a2d1e'],
    'OVERLAY_BROWN_08': 'rgba(209,143,13,0.1)',
    'OVERLAY_GREEN_15': 'rgba(92,166,92,0.17)',
    'OVERLAY_GREEN_40': 'rgba(92,166,92,0.42)',
    'OVERLAY_TEAL_15': 'rgba(64,192,144,0.17)',
    'OVERLAY_ERR2_15': 'rgba(200,90,90,0.17)',
    'OVERLAY_WARN_06': 'rgba(241,196,32,0.08)',
    'OVERLAY_BLACK_30': 'rgba(9,9,9,0.32)',
    'OVERLAY_BLACK_55': 'rgba(9,9,9,0.57)',
    'OVERLAY_BLACK_60': 'rgba(9,9,9,0.62)',
    'OVERLAY_BLACK_65': 'rgba(9,9,9,0.67)',
    'OVERLAY_BLUE_LT_25': 'rgba(160,185,249,0.27)',
    'FONT_XS': '9px',
    'FONT_SM': '10px',
    'FONT_MD': '11px',
    'FONT_LG': '12px',
    'FONT_XL': '13px',
    'FONT_2XL': '14px',
    'FONT_3XL': '18px',
    'FONT_4XL': '20px',
    'FONT_HEADING': '15px',
    'FONT_INPUT': '16px',
    'FONT_ICON': '17px',
    'FONT_ICON_LG': '24px',
    'FONT_CLOUD_1': '11px',
    'FONT_CLOUD_2': '13px',
    'FONT_CLOUD_3': '15px',
    'FONT_CLOUD_4': '18px',
    'FONT_CLOUD_5': '22px',
    'FONT_CLOUD_6': '27px',
    'COLOR_LIGHTBOX_TEXT_HI': '#ffffff',
    'COLOR_LIGHTBOX_TEXT': '#cccccc',
    # ── The rest of the fixed "cinema" family ────────────────────────────────
    # IDENTICAL in all three palettes ON PURPOSE, exactly like the four tokens
    # above. The preview overlay is a deliberately fixed-dark surface in EVERY
    # theme, so a foreground painted on it cannot come from a palette-tuned
    # token: Daylight's are chosen for a LIGHT app background, and measured
    # against the card they collapse — the Back button landed at 1.06:1
    # (invisible), the keyboard-hint chips and poster wells rendered as WHITE
    # boxes on the dark card, and the state glyphs at 1.24:1.
    # Any new role that paints on COLOR_LIGHTBOX_BG/_HEADER takes its colour
    # from this family; tests/test_lightbox_surface_contrast.py measures every
    # one of them against the surface it actually lands on.
    # NOT yet extended to the TRAILMAP_* family: the Explore trail-map mixes
    # this dark shell with genuine app-surface regions, so which surface each
    # of its roles lands on is a real per-role question — its own pass.
    'COLOR_LIGHTBOX_LINK': '#aad4ff',
    'COLOR_LIGHTBOX_MUTED': '#9aa0ab',
    'COLOR_LIGHTBOX_FAINT': '#8f96a1',
    'COLOR_LIGHTBOX_SUNKEN': '#15151f',
    'COLOR_LIGHTBOX_LINE': '#3a3a4e',
    'COLOR_LIGHTBOX_BORDER': '#43435a',
    'COLOR_LIGHTBOX_ACCENT': '#6cb6ff',
    'COLOR_LIGHTBOX_FILL': '#1f6fc7',
    'COLOR_LIGHTBOX_FILL_HOVER': '#2f7fd6',
    'COLOR_LIGHTBOX_ON_FILL': '#ffffff',
    'COLOR_LIGHTBOX_GOLD': '#ffc857',
    'COLOR_LIGHTBOX_OK': '#5fd08a',
}


# ---------------------------------------------------------------------------
# Midnight is DERIVED (#296)
# ---------------------------------------------------------------------------
# The dict above is kept as ``_MIDNIGHT_LEGACY`` — the hand-authored values, no
# longer used for rendering — because it is the record of what the palette was
# before the Radix/DTCG restructure, and the conformance test diffs against it.
#
# ``MIDNIGHT`` now resolves from ``tokens/midnight.tokens.json``: six scale
# choices, 44 semantic roles, and the ~140 legacy names bridged onto them. The
# non-colour entries (FONT_* type scale, BACKDROP_TINTS) are not part of the
# colour system and pass through unchanged.
from metatv.gui.tokens.loader import build_legacy_palette as _build

_TOKENS_DIR = _Path(__file__).parent / "tokens"

def _derive(name: str, legacy: dict[str, TokenValue]) -> dict[str, TokenValue]:
    """Resolve a DTCG palette, carrying over the non-colour entries.

    ``FONT_*`` (a type SCALE, not colours) and the fixed-dark ``COLOR_LIGHTBOX_*``
    family are theme-invariant by design, so they come from the legacy dict
    untouched. Everything else is derived from the token file.
    """
    return {
        **{k: v for k, v in legacy.items()
           if k.startswith("FONT_") or k.startswith("COLOR_LIGHTBOX_")
           # Image scrims: black in EVERY theme. They darken a poster so text
           # can sit on it, so they are a property of the image, not the
           # palette — and Radix's dark alpha scales are white-based, so
           # deriving them inverted every one into a pale wash.
           or k.startswith("OVERLAY_BLACK_")
           or not isinstance(v, str)},
        **_build(_TOKENS_DIR / f"{name}.tokens.json"),
    }


MIDNIGHT: dict[str, TokenValue] = _derive("midnight", _MIDNIGHT_LEGACY)

_DAYLIGHT_LEGACY: dict[str, TokenValue] = {
    'COLOR_TEXT_HI': '#0d0d0d',
    'COLOR_TEXT': '#242424',
    'COLOR_TEXT_2': '#1a1a1a',
    'COLOR_TEXT_LOW': '#454545',
    'COLOR_DIM': '#5c5c5c',
    'COLOR_DIM_2': '#707070',
    'COLOR_MUTED': '#7a7a7a',
    'COLOR_DISABLED': '#8f8f8f',
    'COLOR_MUTED_2': '#9b9b9b',
    'COLOR_FAINT': '#b0b0b0',
    'COLOR_GRAY': '#6e6e6e',
    'COLOR_LIGHTGRAY': '#3a3a3a',
    'COLOR_BORDER': '#d6d6da',
    'COLOR_LINE': '#e3e3e7',
    'COLOR_LINE_DARK': '#edeef1',
    'COLOR_BG_BAR': '#f1f2f4',
    'COLOR_BG_SECTION': '#ececef',
    'COLOR_ACCENT': '#073256',
    'COLOR_ACCENT_HOVER': '#0a4a82',
    # NOT the text ramp: Daylight's COLOR_TEXT_HI is near-black, which on this
    # navy accent reads at ~1.2:1. See the COLOR_ON_ACCENT note in the module
    # docstring — the accent is a FILL in every palette, so its foreground is
    # a separate token from the on-background text ramp.
    'COLOR_ON_ACCENT': '#ffffff',
    'COLOR_OK': '#2e7d32',
    'COLOR_WARN': '#96690a',
    'COLOR_ERR': '#c62828',
    'COLOR_ERR_2': '#b3392b',
    'COLOR_GOLD': 'gold',
    'COLOR_ACCENT_BLUE': '#002e7e',
    'COLOR_ACCENT_BLUE_2': '#88aaff',
    'COLOR_ACCENT_BLUE_3': '#002d86',
    'COLOR_ACCENT_GREEN': '#123624',
    'COLOR_ACCENT_PURPLE': '#39185a',
    'COLOR_ACCENT_ORANGE': '#432501',
    'COLOR_ACCENT_ORANGE_FADED': '#f0a04077',
    'COLOR_ACCENT_TEAL': '#0c3928',
    'COLOR_ACCENT_BROWN': '#412406',
    'COLOR_BTN_SAVE': '#2255cc',
    'COLOR_BTN_SAVE_HOVER': '#3366dd',
    'COLOR_EXCLUSIONS_ACTIVE': '#0b3732',
    'OVERLAY_ORANGE_12': 'rgba(240,160,64,0.13)',
    'OVERLAY_EXCLUSIONS_10': 'rgba(42,157,143,0.11)',
    'OVERLAY_EXCLUSIONS_18': 'rgba(42,157,143,0.19)',
    'OVERLAY_ORANGE_10': 'rgba(240,160,64,0.11)',
    'OVERLAY_ORANGE_18': 'rgba(240,160,64,0.19)',
    'OVERLAY_03': 'rgba(0,0,0,0.03)',
    'OVERLAY_04': 'rgba(0,0,0,0.04)',
    'OVERLAY_05': 'rgba(0,0,0,0.05)',
    'OVERLAY_08': 'rgba(0,0,0,0.08)',
    'OVERLAY_10': 'rgba(0,0,0,0.10)',
    'OVERLAY_15': 'rgba(0,0,0,0.15)',
    'OVERLAY_18': 'rgba(0,0,0,0.18)',
    'OVERLAY_40': 'rgba(255,255,255,0.41)',
    'OVERLAY_55': 'rgba(255,255,255,0.56)',
    'OVERLAY_ACCENT_35': 'rgba(34,136,221,0.36)',
    'OVERLAY_ACCENT_50': 'rgba(34,136,221,0.51)',
    'OVERLAY_POPUP': 'rgba(250,250,252,0.98)',
    'OVERLAY_BLUE_10': 'rgba(68,136,255,0.11)',
    'OVERLAY_BLUE_15': 'rgba(68,136,255,0.16)',
    'OVERLAY_BLUE_20': 'rgba(68,136,255,0.21)',
    'OVERLAY_BLUE_25': 'rgba(68,136,255,0.26)',
    'OVERLAY_BLUE_40': 'rgba(68,136,255,0.41)',
    'OVERLAY_BLUE_60': 'rgba(68,136,255,0.61)',
    'OVERLAY_ERR': 'rgba(224,80,80,0.21)',
    'OVERLAY_ERR_15': 'rgba(224,80,80,0.16)',
    'OVERLAY_PLATFORM_BADGE': 'rgba(60,120,180,0.51)',
    'COLOR_QUALITY_UHD': '#7755cc',
    'COLOR_QUALITY_FHD': '#3388dd',
    'COLOR_QUALITY_HD': '#229977',
    'COLOR_QUALITY_RAW': '#cc8822',
    'COLOR_QUALITY_LIVE': '#bb9900',
    # Outline-chip variants (#257) — same hue, DARKENED (not brightened —
    # Daylight's background is light) so text/border clears 4.5:1 against
    # COLOR_BG_SECTION. RAW/LIVE are inherently close hues (0.036 apart in
    # HSL — true of the base COLOR_QUALITY_RAW/LIVE pair too, which relies
    # entirely on a lightness gap to stay distinguishable) and the required
    # darkening compresses that gap; flagged in the PR body rather than
    # silently over-darkening LIVE to force more separation.
    'COLOR_QUALITY_OUTLINE_UHD': '#2a1954',
    'COLOR_QUALITY_OUTLINE_FHD': '#0c2b49',
    'COLOR_QUALITY_OUTLINE_HD': '#0b3227',
    'COLOR_QUALITY_OUTLINE_RAW': '#342309',
    'COLOR_QUALITY_OUTLINE_LIVE': '#302700',
    'COLOR_AUDIO_BADGE': '#556633',
    'COLOR_MOOD_LIKE_BG': '#2ecc71',
    'COLOR_MOOD_LIKE_FG': '#1a7a43',
    'COLOR_MOOD_CURIOUS_BG': '#27ae60',
    'COLOR_MOOD_CURIOUS_FG': '#155a2e',
    'COLOR_MOOD_NOTFORME_BG': '#c0392b',
    'COLOR_MOOD_NOTFORME_FG': '#f5a5a0',
    'COLOR_MOOD_DISLIKE_BG': '#e74c3c',
    'COLOR_MOOD_TRASH_BG': '#5a1a1a',
    'COLOR_MOOD_WATCH_BG': '#1a3a5a',
    'COLOR_MOOD_EXPLORE_BG': '#1a3a1a',
    'COLOR_MOOD_EXPLORE_FG': '#88cc88',
    'COLOR_NOTIFY_ERR_BG': '#fdecea',
    'COLOR_NOTIFY_ERR_BORDER': '#8a0000',
    'COLOR_NOTIFY_OK_BG': '#e8f5e9',
    'COLOR_NOTIFY_OK_BORDER': '#004700',
    'COLOR_NOTIFY_WARN_BG': '#fff6e0',
    'COLOR_NOTIFY_WARN_BORDER': '#432400',
    'COLOR_NOTIFY_INFO_BG': '#e8f0fe',
    'COLOR_LIGHTBOX_BG': '#1e1e2e',
    'COLOR_LIGHTBOX_HEADER': '#2a2a3e',
    'COLOR_BANNER_YEL_BG': '#fdf6d8',
    'COLOR_BANNER_YEL_FG': '#6b5400',
    'COLOR_BANNER_YEL_BORDER': '#c9a227',
    'COLOR_BANNER_YEL_BG_HOVER': '#faedb0',
    'COLOR_BANNER_YEL_BORDER_HOVER': '#a9860f',
    'COLOR_PPV_ACCENT': '#ff6b35',
    'COLOR_FACET_GENRE': '#0e3b17',
    'COLOR_FACET_LANGUAGE': '#083833',
    'COLOR_FACET_SUBTITLE': '#10352e',
    'COLOR_FACET_DUB': '#05364c',
    'COLOR_FACET_FORMAT': '#352811',
    'COLOR_FACET_REGION': '#3c2800',
    'COLOR_FACET_PLATFORM': '#3700db',
    'COLOR_FACET_DECADE': '#002f77',
    'COLOR_FACET_QUALITY': '#192d41',
    'COLOR_FACET_COLLECTION': '#6d062e',
    'COLOR_RECIPE_BG': '#f4f5f7',
    'COLOR_RECIPE_PANEL_BG': '#eef0f3',
    'COLOR_RECIPE_TEXT': '#202226',
    'COLOR_RECIPE_MUTED': '#5b626f',
    'COLOR_RECIPE_MUTED_2': '#8991a0',
    'OVERLAY_RECIPE_SELECTED': 'rgba(245,183,61,0.09)',
    'OVERLAY_SELECTION': 'rgba(68,136,255,0.17)',
    'COLOR_RED_BRIGHT': '#ff8888',
    'COLOR_ERR_MUTED': '#3f2020',
    'COLOR_GOLD_LIGHT': '#352c00',
    'COLOR_PREF_NUDGE': '#173717',
    'COLOR_ACCENT_BLUE_LIGHT': '#aad4ff',
    'COLOR_BG_CARD': '#eef0f2',
    'COLOR_BG_DEEP': '#111111',
    'COLOR_SURFACE_LIGHT': '#f5f5f5',
    'COLOR_SURFACE_LIGHT_2': '#e0e0e0',
    'COLOR_SURFACE_LIGHT_3': '#d0d0d0',
    'BACKDROP_TINTS': ['#1a3a5c', '#2d4a1e', '#4a1e2d', '#2d1e4a', '#1e4a3a', '#3a2d1e'],
    'OVERLAY_BROWN_08': 'rgba(204,136,0,0.09)',
    'OVERLAY_GREEN_15': 'rgba(80,160,80,0.16)',
    'OVERLAY_GREEN_40': 'rgba(80,160,80,0.41)',
    'OVERLAY_TEAL_15': 'rgba(51,187,136,0.16)',
    'OVERLAY_ERR2_15': 'rgba(204,68,68,0.16)',
    'OVERLAY_WARN_06': 'rgba(255,200,0,0.07)',
    'OVERLAY_BLACK_30': 'rgba(0,0,0,0.31)',
    'OVERLAY_BLACK_55': 'rgba(0,0,0,0.56)',
    'OVERLAY_BLACK_60': 'rgba(0,0,0,0.61)',
    'OVERLAY_BLACK_65': 'rgba(0,0,0,0.66)',
    'OVERLAY_BLUE_LT_25': 'rgba(136,170,255,0.26)',
    'FONT_XS': '9px',
    'FONT_SM': '10px',
    'FONT_MD': '11px',
    'FONT_LG': '12px',
    'FONT_XL': '13px',
    'FONT_2XL': '14px',
    'FONT_3XL': '18px',
    'FONT_4XL': '20px',
    'FONT_HEADING': '15px',
    'FONT_INPUT': '16px',
    'FONT_ICON': '17px',
    'FONT_ICON_LG': '24px',
    'FONT_CLOUD_1': '11px',
    'FONT_CLOUD_2': '13px',
    'FONT_CLOUD_3': '15px',
    'FONT_CLOUD_4': '18px',
    'FONT_CLOUD_5': '22px',
    'FONT_CLOUD_6': '27px',
    'COLOR_LIGHTBOX_TEXT_HI': '#ffffff',
    'COLOR_LIGHTBOX_TEXT': '#cccccc',
    # ── The rest of the fixed "cinema" family ────────────────────────────────
    # IDENTICAL in all three palettes ON PURPOSE, exactly like the four tokens
    # above. The preview overlay is a deliberately fixed-dark surface in EVERY
    # theme, so a foreground painted on it cannot come from a palette-tuned
    # token: Daylight's are chosen for a LIGHT app background, and measured
    # against the card they collapse — the Back button landed at 1.06:1
    # (invisible), the keyboard-hint chips and poster wells rendered as WHITE
    # boxes on the dark card, and the state glyphs at 1.24:1.
    # Any new role that paints on COLOR_LIGHTBOX_BG/_HEADER takes its colour
    # from this family; tests/test_lightbox_surface_contrast.py measures every
    # one of them against the surface it actually lands on.
    # NOT yet extended to the TRAILMAP_* family: the Explore trail-map mixes
    # this dark shell with genuine app-surface regions, so which surface each
    # of its roles lands on is a real per-role question — its own pass.
    'COLOR_LIGHTBOX_LINK': '#aad4ff',
    'COLOR_LIGHTBOX_MUTED': '#9aa0ab',
    'COLOR_LIGHTBOX_FAINT': '#8f96a1',
    'COLOR_LIGHTBOX_SUNKEN': '#15151f',
    'COLOR_LIGHTBOX_LINE': '#3a3a4e',
    'COLOR_LIGHTBOX_BORDER': '#43435a',
    'COLOR_LIGHTBOX_ACCENT': '#6cb6ff',
    'COLOR_LIGHTBOX_FILL': '#1f6fc7',
    'COLOR_LIGHTBOX_FILL_HOVER': '#2f7fd6',
    'COLOR_LIGHTBOX_ON_FILL': '#ffffff',
    'COLOR_LIGHTBOX_GOLD': '#ffc857',
    'COLOR_LIGHTBOX_OK': '#5fd08a',
}



GRAPHITE: dict[str, TokenValue] = _derive("graphite", _GRAPHITE_LEGACY)
DAYLIGHT: dict[str, TokenValue] = _derive("daylight", _DAYLIGHT_LEGACY)

PALETTES: dict[str, dict[str, TokenValue]] = {
    "Midnight": MIDNIGHT,
    "Graphite": GRAPHITE,
    "Daylight": DAYLIGHT,
}

DEFAULT_PALETTE = "Midnight"

# Each palette's kind — "dark" or "light" — drives the background/surface
# luminance guard in tests/test_palette_completeness.py (dark backgrounds must
# stay dark, light backgrounds must stay light; this is the assertion that
# makes a copy-paste-and-forget-to-convert miss impossible to ship).
PALETTE_KIND: dict[str, str] = {
    "Midnight": "dark",
    "Graphite": "dark",
    "Daylight": "light",
}

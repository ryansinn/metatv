"""Every custom ``Qt.ItemDataRole`` the channel list uses, in one place.

Split out of :mod:`channel_list_model` when grouping moved to
:mod:`channel_list_grouping`: both modules need these numbers, and leaving them
in the model meant the grouping module had to import from the module that
imports IT — a cycle Python resolves by failing at load.

They are also exactly the kind of thing CLAUDE.md's lookup-table rule is about.
A role is an integer offset from ``UserRole``, and two modules each holding
their own idea of which offset means what is a class of bug with no symptom
until a row renders the wrong field.

``channel_list_model`` re-exports these (declared in its ``__all__``, never
silenced with ``noqa``) so the sixty-five existing import sites keep working.
New code should import from HERE, the module that defines them.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt

# Custom role: the row's display text as colour-marked HTML.  The playback-state
# separator glyph (▶/✓) is wrapped in a colour <span> so ChannelRowDelegate can
# paint it in the Resume-orange / watched-green token while the rest of the row
# keeps the default (or dimmed) foreground.  DisplayRole stays PLAIN text (used for
# size hints, accessibility, and the model tests).
CHANNEL_HTML_ROLE = Qt.ItemDataRole.UserRole + 5

# Custom roles used only by the opt-in "Group by type" mode (see set_grouped()):
#   ROW_KIND_ROLE     → "header" for a section header row, "channel" for a normal row.
#   SECTION_TYPE_ROLE → on a header row, the media_type the section groups ("movie"/…).
# Both return "channel"/None in the default flat mode, so callers can branch safely.
ROW_KIND_ROLE = Qt.ItemDataRole.UserRole + 6
SECTION_TYPE_ROLE = Qt.ItemDataRole.UserRole + 7

# Structured (non-composed) roles — one field each — added for
# ChannelRowDelegate's density-aware layout (compact/comfy/comfy_plus row
# rendering). DisplayRole and CHANNEL_HTML_ROLE above are UNCHANGED and keep
# serving every existing reader (tests, accessibility, header rows); these
# roles let the delegate lay out/elide/chip-paint individual fields instead of
# parsing the composed string. Return None (via the default data() fallthrough)
# on header rows — only "channel" kind rows populate them.
TITLE_ROLE = Qt.ItemDataRole.UserRole + 8         # detected_title or name (str)
YEAR_ROLE = Qt.ItemDataRole.UserRole + 9          # detected_year or "" (str)
QUALITY_TOKEN_ROLE = Qt.ItemDataRole.UserRole + 10  # raw detected_quality token or ""
LANGUAGE_ROLE = Qt.ItemDataRole.UserRole + 11     # detected_region code or ""
RATING_ROLE = Qt.ItemDataRole.UserRole + 12       # user_rating: -1, 0, or 1 (int)
CATEGORY_ROLE = Qt.ItemDataRole.UserRole + 13     # category or "" (str)
MEDIA_ICON_ROLE = Qt.ItemDataRole.UserRole + 14   # resolved media-type glyph (str)
FAV_GLYPH_ROLE = Qt.ItemDataRole.UserRole + 15    # resolved favorite/unfavorite glyph (str)
PLAYBACK_GLYPH_ROLE = Qt.ItemDataRole.UserRole + 16  # playback state glyph: ·/▶/✓ (str)
PLAYBACK_GLYPH_COLOR_ROLE = Qt.ItemDataRole.UserRole + 17  # playback glyph color token or None
MATCH_MARKER_ROLE = Qt.ItemDataRole.UserRole + 18  # unviewed watch-for match marker 🚨 (str)
PLOT_ROLE = Qt.ItemDataRole.UserRole + 19          # MetadataDB.plot text or "" (str) — Comfy+ only
POSTER_URL_ROLE = Qt.ItemDataRole.UserRole + 20    # MetadataDB.poster_url or "" (str) — thumbnail source
# Collapse-variants "×N" badge count — ChannelListDTO.variant_count (>1 only
# when Settings → Interface → "Collapse quality/language versions" is on AND
# this row represents a collapsed content_key group). 1 (no badge) otherwise.
VARIANT_COUNT_ROLE = Qt.ItemDataRole.UserRole + 21
# Category-marker cleanup roles (Comfy/Comfy+ line 1 right-group + collection chip).
# NOTE: numbered from 22 — 21 belongs to VARIANT_COUNT_ROLE above. Two parallel
# slices both claimed 21; asking for the primary language returned the variant
# COUNT (an int), which blew up in QFontMetrics. Keep these unique.
# See ChannelDB.detected_collection(_language|_subdub) in database.py for provenance.
PRIMARY_LANGUAGE_ROLE = Qt.ItemDataRole.UserRole + 22    # detected_prefix or "" — the channel's OWN (honest) language
SECONDARY_LANGUAGE_ROLE = Qt.ItemDataRole.UserRole + 23  # detected_collection_language or "" — category's disagreeing language marker
SUBTITLE_MARKER_ROLE = Qt.ItemDataRole.UserRole + 24     # detected_collection_subdub or "" — e.g. "AR-SUB"
COLLECTION_ROLE = Qt.ItemDataRole.UserRole + 25          # detected_collection or "" — clean category (marker stripped)
# Genre chip (comfy line 2's taxonomy group, #257 Part C) — ChannelDB.detected_genre,
# the FIRST canonical genre segment, computed once at ingestion (see database.py);
# read directly here, never re-derived at render.
GENRE_ROLE = Qt.ItemDataRole.UserRole + 26                # detected_genre or ""
# EVERY canonical genre segment — ChannelDB.detected_genres, computed in the same
# ingestion pass as detected_genre. The row paints up to _MAX_GENRES of them
# (#298); GENRE_ROLE above stays the single-genre fallback for rows ingested
# before the column existed and not yet re-swept.
GENRES_ROLE = Qt.ItemDataRole.UserRole + 27               # tuple[str, ...] (possibly empty)

#: Sport and league — same model, same delegate as every other row, because the
#: Sports view IS the channel list with a filter on it. Empty on non-sports rows.
SPORT_ROLE = Qt.ItemDataRole.UserRole + 29
#: ``(start, stop)`` for a dated fixture, or None. A PAIR rather than two roles:
#: the two ends are only ever read together, by one predicate, and splitting
#: them is how a caller ends up asking whether something is on now with half
#: the window.
EVENT_WINDOW_ROLE = Qt.ItemDataRole.UserRole + 35
LEAGUE_ROLE = Qt.ItemDataRole.UserRole + 30

#: Normalised media kind — "live" / "movie" / "series" / "" — read straight off
#: the stored ``media_type``. The V3 row treats kind as STRUCTURAL (it picks the
#: kind mark, the artwork aspect, and the first word of the meta line), and a
#: structural decision cannot be made from ``MEDIA_ICON_ROLE``: that role is a
#: display glyph the host supplies, so reading a kind back out of it would be
#: re-deriving a stored fact from its own rendering.
MEDIA_KIND_ROLE = Qt.ItemDataRole.UserRole + 28


#: Row kinds that are a LABEL rather than a result — a section header, and the
#: matched-person sub-heading under Cast & Crew. Both want the same treatment
#: everywhere: one line of HTML, no artwork, nothing to click.
#:
#: A SET here, not repeated `== "header"` tests at each site. The model grew a
#: third row kind and the delegate's three branches did not, so sub-headings
#: shipped painted as CHANNELS — 46px instead of 19, with empty poster and
#: title columns. Guard: tests/test_subheading_delegate_rendering.py.
LABEL_ROW_KINDS = frozenset({"header", "person"})


# ── Section-band roles ──────────────────────────────────────────────────────
#
# The header is PAINTED, not composed as rich text, so the delegate needs its
# parts rather than a finished string. A `flex:1` hairline between the label and
# the count is the specific thing that cannot be expressed in Qt rich text, and
# its absence is what left the band looking empty across the width.
SECTION_LABEL_ROLE = Qt.ItemDataRole.UserRole + 31        # str, already uppercased
SECTION_COUNT_ROLE = Qt.ItemDataRole.UserRole + 32        # int, results in the section
SECTION_WORD_ONLY_ROLE = Qt.ItemDataRole.UserRole + 33   # bool, or None when no search
SECTION_COLLAPSED_ROLE = Qt.ItemDataRole.UserRole + 34    # bool

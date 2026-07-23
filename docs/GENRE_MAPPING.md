# MetaTV Genre Mapping

The single auditable record of how raw provider `genre` strings consolidate into
MetaTV's canonical genre vocabulary — **which raw value folds where, and why.**

This chart was reviewed and signed off batch-by-batch by the project owner on
2026-07-22 (PR #153) and is applied exactly as amended by that sign-off.

## What this covers (and does not)

**Presentation layer only.** This governs how genre *labels* are displayed and
collapsed into filter/facet values. Raw source metadata (`metadata.genres`,
provider `raw_data["genre"]`) is **never rewritten** — originals stay fully
recoverable. The single implementation chokepoint is `_GENRE_NORM` /
`normalize_genre()` in `metatv/core/filter_utils.py` (lookup-tables rule); this
document is its human-readable mirror.

- **647 distinct raw `genre` values** in the corpus, covering **456,872**
  channel-genre associations.
- Consolidated outcome: **~38 canonical genres + a 325-value keep-as-is tail.**
  The canonical set captures **455,400 / 456,872 associations (99.7%)**; the
  entire keep-as-is tail is only **1,472 associations (0.3%)** — the mess is
  long-tail *values*, not viewers' content.
- This PR adds **129 new folds** (byte-exact rows below) on top of the ~158
  multilingual variants `_GENRE_NORM` already folded, plus **6 corrections** and
  **10 new canonicals** (7 individual + 3 Drama-led compounds).

## Hard rules (owner)

1. **Extremely conservative — never join distinct concepts.** A compound
   (`Sci-Fi & Fantasy`, `Action & Adventure`, `Drama & Comedy`) is a *first-class*
   genre, never split into or absorbed by its components. Only *notation variants
   of the same genre* fold together.
2. **Uncertain → keep raw.** Anything not confidently a notation-variant stays
   raw (Tag Janitor food later). A long keep-as-is tail is expected and fine.

## Amendments honored (from the sign-off log)

- **`Soap` renamed to display `Soap Opera`** everywhere it is produced; the
  telenovela family (`Telenovela` / `Telenowela` / `Såpa`) folds in.
- **`TV Show` keeps its name** (contents include non-series programs; a genre
  "TV Series" would collide with `media_type=series`).
- **Drama-containing compounds are Drama-led:** the chart's alphabetical
  `Comedy & Drama` / `Crime & Drama` become **`Drama & Comedy`** / **`Drama &
  Crime`** (owner: Drama is the common thread, keeps them adjacent).
  `Drama & Romance` is already Drama-led.
- **6 corrections** to pre-existing `_GENRE_NORM` entries (see the Corrections
  section): `variety` / `underhållning` / Persian `اجتماعی` mappings removed
  (kept raw); `tävling` → Game Show; `biografi` / `Biografi` → Biography;
  `children & family` → Family.

## Class legend

| class | meaning |
|---|---|
| `case` | case / whitespace-only variant (`DRAMA` → Drama) |
| `typo` | misspelling or truncation (`Dram`, `Thrille`, `DRMA`) |
| `noise-suffix` | format-word noise stripped (`Drama series`, `Reality Show`) |
| `separator-variant` | one compound, different separator (`Crime. Drama`) |
| `order-variant` | one compound, different component order (owner pre-approved) |
| `translation` | non-English label (row cites language + literal meaning) |
| `rename` / `correction` / `canonical` | the #153 amendments above |

## Canonical identity & i18n

Canonical identity is a language-neutral **slug** + an English **display name**
(e.g. `drama-comedy` = *Drama & Comedy*). **Only the display name is stored** as
the tag value today (the #143 / #299 convention). The slugs are documented per
canonical in the sign-off chart for a future i18n layer (which would translate
the display name only) and are **intentionally not implemented here** — this PR
changes vocabulary, not storage encoding.

## Doc ↔ code parity (drift guard)

Every fold row in the **Fold map** below is machine-checked against the live
`normalize_genre()` by `tests/test_genre_mapping_parity.py`: the test parses this
file's tables and asserts each `raw → canonical` is exactly what the code
returns, and that every **Kept raw** value is *not* remapped. Doc and code
therefore cannot silently drift.

---

## Fold map

Each subsection is one canonical genre. `raw value` (lowercased) → the section's
`Canonical:` value via `normalize_genre()`.

### Drama

Canonical: `Drama`

| raw value | class | why |
|---|---|---|
| `DRAMA` | case | uppercase of Drama |
| `Dram` | typo | truncation of 'Drama' |
| `Deama` | typo | letter-transposition of 'Drama' |
| `DRMA` | typo | missing-vowel spelling of 'Drama' |
| `Drama series` | noise-suffix | 'series' is a format word, not a genre |
| `ﺓدراما` | translation | Arabic (presentation-form) 'Drama' w/ stray leading char |

### Comedy

Canonical: `Comedy`

| raw value | class | why |
|---|---|---|
| `COMEDY` | case | uppercase of Comedy |
| `humor` | translation | Spanish/intl 'humor' = comedy |

### Crime

Canonical: `Crime`

| raw value | class | why |
|---|---|---|
| `CRIME` | case | uppercase of Crime |
| `ﺟﺮﻳﻤﺔ` | translation | Arabic (presentation-form) 'crime' |
| `Brottslighet` | translation | Swedish 'criminality' = crime |
| `Kriminalistika` | translation | Croatian 'criminology/crime' |

### Documentary

Canonical: `Documentary`

| raw value | class | why |
|---|---|---|
| `DOCUMENTARY` | case | uppercase of Documentary |
| `DOCU` | typo | uppercase truncation of Documentary |
| `docu` | typo | truncation of documentary |
| `Ducomantary` | typo | misspelling of documentary |
| `Ducomentaire` | typo | misspelling of documentaire (Fr) |
| `DOCUMEANTARY` | typo | misspelling of documentary |
| `DOCUMEMTARY` | typo | misspelling of documentary |
| `DOCUMENT` | typo | truncation of Documentary |
| `DOCUMENTARYk` | typo | stray trailing 'k' on Documentary |
| `ﻭﺛﺎﺋﻘﻲ` | translation | Arabic (presentation-form) 'documentary' |
| `Dokument` | translation | German/Swedish/Polish 'document(ary)' |
| `Dokumentarno` | translation | Croatian/Slovene 'documentary' |
| `Documentarni` | translation | Croatian 'documentary' |
| `Dokumentarna serija` | translation | Croatian 'documentary series' |
| `Dokumentalizowany` | translation | Polish 'documentary(-style)' |
| `belgeseli` | translation | Turkish 'documentary' (belgesel + suffix) |

### Sci-Fi & Fantasy

Canonical: `Sci-Fi & Fantasy`

| raw value | class | why |
|---|---|---|
| `naučna fantastika i fantazija` | translation | Croatian 'science fiction and fantasy' (the compound) |
| `Επ. Φαντασία - Φαντασίας` | translation | Greek 'Sci. Fiction - Fantasy' (the compound) |

### Mystery

Canonical: `Mystery`

| raw value | class | why |
|---|---|---|
| `MYSTERY` | case | uppercase of Mystery |

### Thriller

Canonical: `Thriller`

| raw value | class | why |
|---|---|---|
| `Thrille` | typo | truncation of Thriller |
| `Thriler` | typo | misspelling of Thriller |
| `ﺗﺸﻮﻳﻖ` | translation | Arabic (presentation-form) 'suspense/thriller' |
| `اثارة` | translation | Arabic 'excitement/thriller' (variant of إثارة) |

### Animation

Canonical: `Animation`

| raw value | class | why |
|---|---|---|
| `كرتون` | translation | Arabic 'cartoon' |
| `كارتون` | translation | Arabic 'cartoon' |
| `Kreskówka` | translation | Polish 'cartoon' |
| `Cartone` | translation | Italian 'cartoon' |

### Romance

Canonical: `Romance`

| raw value | class | why |
|---|---|---|
| `Rpmance` | typo | misspelling of Romance |
| `Liebesfilm` | translation | German 'love film' = romance |
| `ﺭﻭﻣﺎﻧﺴﻲ` | translation | Arabic (presentation-form) 'romantic' |
| `رومنسية` | translation | Arabic 'romance' (variant spelling) |
| `Romansa` | translation | Croatian/Bosnian 'romance' |
| `romansa` | translation | Croatian/Bosnian 'romance' |

### Action

Canonical: `Action`

| raw value | class | why |
|---|---|---|
| `Actio` | typo | truncation of Action |
| `Acción` | translation | Spanish 'action' |

### Kids

Canonical: `Kids`

| raw value | class | why |
|---|---|---|
| `KIDS` | case | uppercase of Kids |
| `Dla dzieci` | translation | Polish 'for children' |

### Family

Canonical: `Family`

| raw value | class | why |
|---|---|---|
| `FAMILY` | case | uppercase of Family |
| `FAMELY` | typo | misspelling of Family |
| `children & family` | correction | compound; was mis-mapped to Kids — 'Family implies children' (#153 fix) |

### Reality

Canonical: `Reality`

| raw value | class | why |
|---|---|---|
| `REALITY-TV` | case | uppercase Reality-TV |
| `reality-tv` | case | lowercase Reality-TV |
| `REALITY` | case | uppercase of Reality |
| `realety` | typo | misspelling of reality |
| `Reality Show` | noise-suffix | 'Show' is a format word; Reality Show = Reality |
| `Reality-TV` | noise-suffix | hyphenated 'Reality TV' |
| `Reality-Show` | noise-suffix | hyphenated 'Reality Show' |
| `Realityseries` | noise-suffix | 'series' format word appended |
| `TELEREALITY` | translation | French 'téléréalité' = reality TV |
| `Gerçeklik` | translation | Turkish 'reality' |

### Sports

Canonical: `Sports`

| raw value | class | why |
|---|---|---|
| `Sportowy` | translation | Polish 'sporting/sports' |

### Adventure

Canonical: `Adventure`

| raw value | class | why |
|---|---|---|
| `ADVENTUR` | typo | truncation of Adventure |

### War & Politics

Canonical: `War & Politics`

| raw value | class | why |
|---|---|---|
| `Krig och Politik` | translation | Swedish 'War and Politics' (och='and') |

### Western

Canonical: `Western`

| raw value | class | why |
|---|---|---|
| `Faroeste` | translation | Portuguese 'western' |

### Science Fiction

Canonical: `Science Fiction`

| raw value | class | why |
|---|---|---|
| `خيال علمي` | translation | Arabic 'science fiction' (pure; NOT the compound) |

### Fantasy

Canonical: `Fantasy`

| raw value | class | why |
|---|---|---|
| `فانتازيا` | translation | Arabic 'fantasy' |
| `Fantasía` | translation | Spanish 'fantasy' |
| `Fantasi` | translation | Swedish/Danish 'fantasy' |

### History

Canonical: `History`

| raw value | class | why |
|---|---|---|
| `Histoey` | typo | misspelling of History |
| `Hostory` | typo | misspelling of History |
| `تاريخ` | translation | Arabic 'history' |
| `Historie` | translation | German/Danish/Norwegian 'history' |
| `Istorija` | translation | Croatian/Baltic 'history' |

### Music

Canonical: `Music`

| raw value | class | why |
|---|---|---|
| `موسيقي` | translation | Arabic 'music' |
| `Piosenki` | translation | Polish 'songs' |
| `موسيقى` | translation | Arabic 'music' |

### Soap Opera

Canonical: `Soap Opera`

| raw value | class | why |
|---|---|---|
| `Såpa` | translation | Swedish 'soap opera' |
| `Telenowela` | translation | Polish 'telenovela' = soap opera |
| `Telenovela` | translation | 'telenovela' = soap opera |
| `Soap` | rename | canonical renamed Soap → Soap Opera (owner amendment) |

### TV Show

Canonical: `TV Show`

| raw value | class | why |
|---|---|---|
| `Serial` | noise-suffix | 'serial' = TV series (verified: PK dramas) |
| `Mini Serial` | noise-suffix | 'mini serial' = miniseries (format) |
| `برنامج` | translation | Arabic 'program' |
| `برنامج تلفزيوني` | translation | Arabic 'television program' |
| `سریال` | translation | Persian 'serial/TV series' (verified: PK/IR series) |
| `سريال` | translation | Arabic/Persian 'serial/TV series' |
| `برامج تليفزيوني` | translation | Arabic 'TV programs' |
| `Série-TV` | translation | French 'TV series' |
| `Série-Tv` | translation | French 'TV series' (case) |
| `serie-tv` | translation | French/Italian 'TV series' (lowercase) |
| `برنامه` | translation | Persian 'program' |

### Talk Show

Canonical: `Talk Show`

| raw value | class | why |
|---|---|---|
| `TALK-SHOW` | case | uppercase hyphenated Talk-Show |
| `TV Talk Show` | noise-suffix | 'TV' qualifier prepended to Talk Show |
| `Talk-Show` | separator-variant | hyphen instead of space |
| `حوار` | translation | Arabic 'talk/interview' (verified: talk-show channels) |
| `تاک شو` | translation | Persian 'talk show' |

### War

Canonical: `War`

| raw value | class | why |
|---|---|---|
| `Krig` | translation | Swedish/Danish/Norwegian 'war' |
| `ﺣﺮﺏ` | translation | Arabic (presentation-form) 'war' |

### News

Canonical: `News`

| raw value | class | why |
|---|---|---|
| `أخبار` | translation | Arabic 'news' |

### Drama & Comedy

Canonical: `Drama & Comedy`

| raw value | class | why |
|---|---|---|
| `دراما .كوميديا` | separator-variant | Arabic 'Drama. Comedy' |
| `دراما كوميديا` | order-variant | Arabic 'Drama Comedy' -> alphabetical Comedy & Drama |
| `دراما كوميدي` | order-variant | Arabic 'Drama Comedy' (masc.) |
| `كوميدي ﺩﺭاﻣﺎ` | order-variant | Arabic 'Comedy Drama' |
| `ﻛﻮﻣﻴﺪﻱ ﺩﺭاﻣﺎ` | order-variant | Arabic (presentation) 'Comedy Drama' |

### Politics

Canonical: `Politics`

| raw value | class | why |
|---|---|---|
| `Politik` | translation | Swedish/German 'politics' |
| `Polityczny` | translation | Polish 'political' |
| `Politicki` | translation | Croatian 'political' |

### Biography

Canonical: `Biography`

| raw value | class | why |
|---|---|---|
| `BIOGRAPHY` | case | uppercase of Biography |
| `ﺳﻴﺮﺓ ﺫاﺗﻴﺔ` | translation | Arabic (presentation-form) 'autobiography/biography' |
| `Biograficzny` | translation | Polish 'biographical' |
| `سيرة ذاتية` | translation | Arabic 'autobiography' |
| `سيرة` | translation | Arabic 'life story/biography' |
| `Biografija` | translation | Croatian/Serbian 'biography' |
| `Biografi` | translation | Swedish/Danish 'biography' (currently mis-mapped to History) |

### Game Show

Canonical: `Game Show`

| raw value | class | why |
|---|---|---|
| `Game show` | case | lowercase 's' in Show |
| `GameShow` | separator-variant | missing space |
| `Gameshow` | separator-variant | missing space + case |
| `GAME-SHOW` | separator-variant | hyphen + uppercase |
| `Teleturniej` | translation | Polish 'TV game/quiz show' |
| `tävling` | correction | Swedish 'competition'; was mis-mapped to Reality (#153 fix) |

### Drama & Romance

Canonical: `Drama & Romance`

| raw value | class | why |
|---|---|---|
| `drama - romance` | separator-variant | dash separator, Drama+Romance |
| `Drama Romance` | separator-variant | space-separated Drama+Romance |
| `دراما ﺭﻭﻣﺎﻧﺴﻲ` | order-variant | Arabic 'Drama Romance' |
| `Romance Drama` | order-variant | 'Romance Drama' -> alphabetical Drama & Romance |
| `ﺭﻭﻣﺎﻧﺴﻲ .دراما` | order-variant | Arabic 'Romance. Drama' |

### Drama & Crime

Canonical: `Drama & Crime`

| raw value | class | why |
|---|---|---|
| `Crime. Drama` | separator-variant | dot separator, Crime+Drama |
| `Brottsdrama` | translation | Swedish 'crime drama' (the compound) |
| `kriminalistička drama` | translation | Croatian 'crime/detective drama' |

### Anime

Canonical: `Anime`

| raw value | class | why |
|---|---|---|
| `Amine` | typo | misspelling of Anime |
| `إنمي` | translation | Arabic 'anime' |

### Adult

Canonical: `Adult`

| raw value | class | why |
|---|---|---|
| `Adult` | canonical | 20,368 ch — new canonical, add to vocabulary |

### Music Show

Canonical: `Music Show`

| raw value | class | why |
|---|---|---|
| `Music Show` | canonical | new canonical, kept distinct from Music |

### TV Movie

Canonical: `TV Movie`

| raw value | class | why |
|---|---|---|
| `TV Movie` | canonical | new canonical, distinct format |

---

## Corrections to pre-existing mappings

Six already-shipped `_GENRE_NORM` entries violated the hard rules; #153 fixes
them. The three *remapped* rows also appear in the Fold map above; the three
*now-raw* rows appear in Kept raw below.

| raw value | was | now | why |
|---|---|---|---|
| `Soap` (canonical) | Soap | **Soap Opera** | display rename (owner amendment) |
| `biografi` / `Biografi` | History | **Biography** | Biography ≠ History |
| `tävling` | Reality | **Game Show** | Game Show is a distinct genre, not Reality |
| `children & family` | Kids | **Family** | a compound absorbed into a component; owner: "Family implies children" |
| `variety` | Talk Show | **(raw)** | Variety ≠ Talk Show — concept merge |
| `underhållning` | Talk Show | **(raw)** | Swedish "entertainment" is broader than Talk Show |
| `اجتماعی` | Drama | **(raw)** | Persian "social" — a concept guess, not a notation variant |

---

## Kept raw (deliberate non-mappings)

The **325-value keep-as-is tail (1,472 channels)** is deliberately *not* folded:
uncertain, multi-genre, mixed-language, or not a genre. Listed verbatim (with the
three now-raw corrections appended) so the non-mapping is auditable. The parity
test asserts none of these is remapped by the live code.

| raw value | reason |
|---|---|
| `Comedy طنز اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Comedy طنز، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Social اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama درام \| اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama درام، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Talk Show تاک شو` | English label + Persian/Arabic multi-genre string |
| `Comedy طنز` | English label + Persian/Arabic multi-genre string |
| `Romance عاشقانه` | English label + Persian/Arabic multi-genre string |
| `Comedy	طنز اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Comedy  کمدی و خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی، اجتماعی، خانوادگی، درام` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی، سرگرمی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی٫ اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama اجتماعی، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama اجتماعی، خانوادگی، درام` | English label + Persian/Arabic multi-genre string |
| `Drama اجتماعی، درام، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama خانوادگی - درام` | English label + Persian/Arabic multi-genre string |
| `Family کمدی \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `History تاریخی` | English label + Persian/Arabic multi-genre string |
| `Mystery درام \| معمایی` | English label + Persian/Arabic multi-genre string |
| `Action اکشن` | English label + Persian/Arabic multi-genre string |
| `Animation ماجراجویی \| فانتزی` | English label + Persian/Arabic multi-genre string |
| `Biography درام، اجتماعی، زندگی‌نامه‌ای` | English label + Persian/Arabic multi-genre string |
| `Comedy  اجتماعی کمدی` | English label + Persian/Arabic multi-genre string |
| `Comedy اجتماعی، کمدی، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Comedy تله تئاترکمدی` | English label + Persian/Arabic multi-genre string |
| `Comedy جتماعی، کمدی، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Comedy خانوادگی، کمدی` | English label + Persian/Arabic multi-genre string |
| `Comedy رئالیتی شو،  کمدی و طنز` | English label + Persian/Arabic multi-genre string |
| `Comedy رئالیتی شو، کمدی، مسابقه` | English label + Persian/Arabic multi-genre string |
| `Comedy ماجراجویی و  کمدی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی . اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی \| ماجرایی \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی ، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی و اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Comedy کمدی، کودک و نوجوان` | English label + Persian/Arabic multi-genre string |
| `Crime  اکشن، کمدی، جنایی` | English label + Persian/Arabic multi-genre string |
| `Crime اکشن، اجتماعی، جنایی` | English label + Persian/Arabic multi-genre string |
| `Crime پلیسی جنایی` | English label + Persian/Arabic multi-genre string |
| `Crime پلیسی ـ اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Crime پلیسی معمایی` | English label + Persian/Arabic multi-genre string |
| `Crime. Mystery جنایی \| رازآلود` | English label + Persian/Arabic multi-genre string |
| `Deama درام، اجتماعی، خانوادگی، ماورایی` | English label + Persian/Arabic multi-genre string |
| `Documentary ماجراجویی \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama  اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama  جنایی، معمایی و پلیسی` | English label + Persian/Arabic multi-genre string |
| `Drama  خانوادگی و اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama  خانوادگی، اجتماعی، درام` | English label + Persian/Arabic multi-genre string |
| `Drama اجتماعی خانوادگی کمدی` | English label + Persian/Arabic multi-genre string |
| `Drama اجتماعی، انقلابی، درام` | English label + Persian/Arabic multi-genre string |
| `Drama اجتماعی، جنایی، درام` | English label + Persian/Arabic multi-genre string |
| `Drama احتماعی، درام` | English label + Persian/Arabic multi-genre string |
| `Drama اکشن، درام، اجتماعی، هیجان‌انگیز` | English label + Persian/Arabic multi-genre string |
| `Drama اکشن، درام، پلیسی، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama تاریخی` | English label + Persian/Arabic multi-genre string |
| `Drama تاریخی درام` | English label + Persian/Arabic multi-genre string |
| `Drama تاریخی، خانوادگی، درام` | English label + Persian/Arabic multi-genre string |
| `Drama تاریخی، خانوادگی، عاشقانه و درام` | English label + Persian/Arabic multi-genre string |
| `Drama خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama خانوادگی  ملودرام` | English label + Persian/Arabic multi-genre string |
| `Drama خانوادگی و درام` | English label + Persian/Arabic multi-genre string |
| `Drama خانوادگی، درام` | English label + Persian/Arabic multi-genre string |
| `Drama خانوادگی، درام، عاشقانه` | English label + Persian/Arabic multi-genre string |
| `Drama داستانی ماجرایی` | English label + Persian/Arabic multi-genre string |
| `Drama درام . پلیسی` | English label + Persian/Arabic multi-genre string |
| `Drama درام \| جنایی` | English label + Persian/Arabic multi-genre string |
| `Drama درام \| عاشقانه \| جنگی` | English label + Persian/Arabic multi-genre string |
| `Drama درام و اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama درام و خانوادگی اجتماعی، پلیسی` | English label + Persian/Arabic multi-genre string |
| `Drama درام پلیسی اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama درام، اجتماعی و خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama درام، اجتماعی، پلیسی، سیاسی` | English label + Persian/Arabic multi-genre string |
| `Drama درام، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama درام، کمدی، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama عاشقانه و درام` | English label + Persian/Arabic multi-genre string |
| `Drama مذهبی، تاریخی، زندگینامه` | English label + Persian/Arabic multi-genre string |
| `Drama معمایی، درام، پلیسی` | English label + Persian/Arabic multi-genre string |
| `Drama ملودرام، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Drama ملودرام، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Drama ورزشی، اجتماعی و کمدی` | English label + Persian/Arabic multi-genre string |
| `Drama کمدی، درام، اجتماعی، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Family تاریخی، درام، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Family خانوادگی . اجتماعی . کمدی` | English label + Persian/Arabic multi-genre string |
| `Family خانوادگی، کمدی` | English label + Persian/Arabic multi-genre string |
| `Family عاشقانه و خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Family کمدی، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Family کمدی، درام، جنگی، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Game Show  مسابقه \| معمایی \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Game Show ریلیتی شو و گیم شو` | English label + Persian/Arabic multi-genre string |
| `Game Show مسابقه \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Game Show مسابقه \| معمایی \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Game Show کمدی \| مسابقه \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Games سرگرمی` | English label + Persian/Arabic multi-genre string |
| `History	تاریخی` | English label + Persian/Arabic multi-genre string |
| `History تاریخی \| جنگی \| حماسی` | English label + Persian/Arabic multi-genre string |
| `History تاریخی و دفاع مقدس` | English label + Persian/Arabic multi-genre string |
| `History تاریخی، درام، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `History تاریخی، درام، جنگی` | English label + Persian/Arabic multi-genre string |
| `History تاریخی، عاشقانه` | English label + Persian/Arabic multi-genre string |
| `History درام تاریخی` | English label + Persian/Arabic multi-genre string |
| `Hostory تاریخی . انیمیشن` | English label + Persian/Arabic multi-genre string |
| `Hostory خانوادگی فانتزی تاریخی` | English label + Persian/Arabic multi-genre string |
| `Kids کمدی، تربیتی، کودک و نوجوان` | English label + Persian/Arabic multi-genre string |
| `Kids کودک` | English label + Persian/Arabic multi-genre string |
| `Kids کودک \| سرگرمی \| موزیکال` | English label + Persian/Arabic multi-genre string |
| `Kids کودک و نوجوان` | English label + Persian/Arabic multi-genre string |
| `Mystery جنایی \| رازآلود` | English label + Persian/Arabic multi-genre string |
| `Mystery جنایی \| معمایی` | English label + Persian/Arabic multi-genre string |
| `Mystery درام جنایی معمایی` | English label + Persian/Arabic multi-genre string |
| `Mystery عاشقانه \| معمایی` | English label + Persian/Arabic multi-genre string |
| `Mystery معمایی، خانوادگی و درام` | English label + Persian/Arabic multi-genre string |
| `Mysytery پلیسی، معمایی، جنایی` | English label + Persian/Arabic multi-genre string |
| `Reality Show رئالیتی شو \| مسابقه \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Reality Show رئالیتی شو، گیم شو، مسابقه` | English label + Persian/Arabic multi-genre string |
| `Reality Show کمدی \| رئالیتی شو` | English label + Persian/Arabic multi-genre string |
| `Reality مسابقه \| رئالیتی شو` | English label + Persian/Arabic multi-genre string |
| `Reality مهیج \| معمایی` | English label + Persian/Arabic multi-genre string |
| `Romance درام \| عاشقانه` | English label + Persian/Arabic multi-genre string |
| `Romance درام، عاشقانه، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Social  خانوادگی و اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Social اجتماعی ، خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Social اجتماعی و پلیسی` | English label + Persian/Arabic multi-genre string |
| `Sport ورزشی` | English label + Persian/Arabic multi-genre string |
| `TALK SHOW تاک شو` | English label + Persian/Arabic multi-genre string |
| `Talk Show تاک شو \| خانوادگی` | English label + Persian/Arabic multi-genre string |
| `Talk Show تاک شو ، کمدی ، ورزشی` | English label + Persian/Arabic multi-genre string |
| `Talk Show مسابقه` | English label + Persian/Arabic multi-genre string |
| `Talk Show کمدی، اجتماعی` | English label + Persian/Arabic multi-genre string |
| `Talk Show گفت‌وگو محور` | English label + Persian/Arabic multi-genre string |
| `War درام \| جنگی` | English label + Persian/Arabic multi-genre string |
| `Drama درام \| جنایی \| اجتماعی` | English label + Persian/Arabic multi-genre string |
| `دراما ﺗﺸﻮﻳﻖ ﻭﺇﺛﺎﺭﺓ` | multi-genre Arabic/Persian string |
| `اجتماعي حواري` | multi-genre Arabic/Persian string |
| `ترفيهي موسيقي حفلات غنائية` | multi-genre Arabic/Persian string |
| `جتماعي حواري` | multi-genre Arabic/Persian string |
| `طبيعة ثقافي علوم وثائقي رومانسي دراما` | multi-genre Arabic/Persian string |
| `واقع برنامج تلفزيوني` | multi-genre Arabic/Persian string |
| `ﻛﻮﻣﻴﺪﻱ ﺩﺭاﻣﺎ إجتماعي` | multi-genre Arabic/Persian string |
| `إخباري سياسي حواري` | multi-genre Arabic/Persian string |
| `برنامج  توك شو حواري` | multi-genre Arabic/Persian string |
| `دراما اجتماعية` | multi-genre Arabic/Persian string |
| `اثارة دراما` | multi-genre Arabic/Persian string |
| `دراما ﺟﺮﻳﻤﺔ ﻭﺇﺛﺎﺭﺓ` | multi-genre Arabic/Persian string |
| `سریال ایرانی` | multi-genre Arabic/Persian string |
| `تاريخي دراما` | multi-genre Arabic/Persian string |
| `.كوميديا` | multi-genre Arabic/Persian string |
| `إثارة وتشويق` | multi-genre Arabic/Persian string |
| `انيميشن \تاريخى` | multi-genre Arabic/Persian string |
| `برنامج ترفيهي` | multi-genre Arabic/Persian string |
| `خانوادگی و اجتماعی` | multi-genre Arabic/Persian string |
| `دراما تاريخي` | multi-genre Arabic/Persian string |
| `دفاع مقدس` | multi-genre Arabic/Persian string |
| `ديني  تاريخي` | multi-genre Arabic/Persian string |
| `رسوم متحركة اطفال` | multi-genre Arabic/Persian string |
| `صانعي المحتوى` | multi-genre Arabic/Persian string |
| `غموض ﺗﺸﻮﻳﻖ ﻭﺇﺛﺎﺭﺓ` | multi-genre Arabic/Persian string |
| `ملودرام اجتماعی` | multi-genre Arabic/Persian string |
| `طبيعة ثقافي علوم وثائقي` | multi-genre Arabic/Persian string |
| `اجتماعي. عائلي` | multi-genre Arabic/Persian string |
| `اجتماعی ، خانوادگی ، درام ، کمدی` | multi-genre Arabic/Persian string |
| `اجتماعی تاریخی جنگی` | multi-genre Arabic/Persian string |
| `اجتماعی مذهبی` | multi-genre Arabic/Persian string |
| `اجتماعی پلیسی` | multi-genre Arabic/Persian string |
| `اجتماعی، جنایی` | multi-genre Arabic/Persian string |
| `اجتماعی، خانوادگی` | multi-genre Arabic/Persian string |
| `اجتماعی، درام، خانوادگی` | multi-genre Arabic/Persian string |
| `اجتماعی، پلیسی` | multi-genre Arabic/Persian string |
| `اجتماعی، کمدی` | multi-genre Arabic/Persian string |
| `اریخی، سیاسی، انقلابی` | multi-genre Arabic/Persian string |
| `انمي عائلي مغامرة` | multi-genre Arabic/Persian string |
| `انمي مغامرة` | multi-genre Arabic/Persian string |
| `اکشن ، جنایی` | multi-genre Arabic/Persian string |
| `اکشن و هیجان انگیز` | multi-genre Arabic/Persian string |
| `اکشن و پلیسی` | multi-genre Arabic/Persian string |
| `اکشن و پلیسی معمایی` | multi-genre Arabic/Persian string |
| `اکشن، پلیسی` | multi-genre Arabic/Persian string |
| `برنامج ديني` | multi-genre Arabic/Persian string |
| `برنامج مسابقات` | multi-genre Arabic/Persian string |
| `تاريخ \دراما` | multi-genre Arabic/Persian string |
| `تاريخ دراما وثائقى` | multi-genre Arabic/Persian string |
| `تاریخی \| مذهبی` | multi-genre Arabic/Persian string |
| `تاریخی حماسی` | multi-genre Arabic/Persian string |
| `تاریخی، اجتماعی` | multi-genre Arabic/Persian string |
| `تاریخی، درام، جنگی` | multi-genre Arabic/Persian string |
| `تاریخی، درام، سیاسی، اجتماعی` | multi-genre Arabic/Persian string |
| `تاریخی، زندگینامه` | multi-genre Arabic/Persian string |
| `تاریخی، عاشقانه` | multi-genre Arabic/Persian string |
| `تشويق دراما` | multi-genre Arabic/Persian string |
| `تشويق وإثارة` | multi-genre Arabic/Persian string |
| `جتماعی، تاریخی، سیاسی` | multi-genre Arabic/Persian string |
| `جتماعی، پلیسی، اکشن` | multi-genre Arabic/Persian string |
| `جريمة غموض` | multi-genre Arabic/Persian string |
| `خانوادگی، اجتماعی` | multi-genre Arabic/Persian string |
| `خانوادگی، عاشقانه` | multi-genre Arabic/Persian string |
| `خانوادگی، پلیسی، اجتماعی` | multi-genre Arabic/Persian string |
| `درام، خانوادگی` | multi-genre Arabic/Persian string |
| `دراما عائلي` | multi-genre Arabic/Persian string |
| `دراما\ رياضي\ سيرة ذاتية` | multi-genre Arabic/Persian string |
| `دراما، رعب، غموض وتشويق.` | multi-genre Arabic/Persian string |
| `رسوم متحركة ديني` | multi-genre Arabic/Persian string |
| `رﺳﻮﻡ ﻣﺘﺤﺮﻛﺔ` | multi-genre Arabic/Persian string |
| `سيرة ذاتية تاريخي` | multi-genre Arabic/Persian string |
| `سيرة ذاتية وثائقي تاريخي دراما` | multi-genre Arabic/Persian string |
| `طنز، اجتماعی` | multi-genre Arabic/Persian string |
| `عائلي كوميدي` | multi-genre Arabic/Persian string |
| `عروسکی، کمدی، تاک شو` | multi-genre Arabic/Persian string |
| `غموض رومانسي اثارة` | multi-genre Arabic/Persian string |
| `قانون ثقافي اجتماعي` | multi-genre Arabic/Persian string |
| `مسابقات ترفيهي` | multi-genre Arabic/Persian string |
| `مسابقه \| معمایی \| موزیکال` | multi-genre Arabic/Persian string |
| `مسابقه ، رئالیتی شو` | multi-genre Arabic/Persian string |
| `مسلسل تلفزيوني تركي` | multi-genre Arabic/Persian string |
| `معمایی ، هیجان انگیز` | multi-genre Arabic/Persian string |
| `معمایی ، پلیسی` | multi-genre Arabic/Persian string |
| `معمایی فیلم اکشن پلیسی` | multi-genre Arabic/Persian string |
| `ملودرام، عاشقانه` | multi-genre Arabic/Persian string |
| `مناسبتی، اجتماعی` | multi-genre Arabic/Persian string |
| `موسيقي وثائقي` | multi-genre Arabic/Persian string |
| `نمایش عروسکی` | multi-genre Arabic/Persian string |
| `پلیسی، اجتماعی` | multi-genre Arabic/Persian string |
| `پلیسی، درام، خانوادگی` | multi-genre Arabic/Persian string |
| `پلیسی، معمایی` | multi-genre Arabic/Persian string |
| `پلیسی، معمایی، اجتماعی` | multi-genre Arabic/Persian string |
| `کمدی و اکشن` | multi-genre Arabic/Persian string |
| `کمدی، درام، سیاسی` | multi-genre Arabic/Persian string |
| `کمدی، فانتزی، خانوادگی` | multi-genre Arabic/Persian string |
| `ﺩﺭاﻣﺎ .ﻣﻐﺎﻣﺮاﺕ` | multi-genre Arabic/Persian string |
| `ﺭﺳﻮﻡ ﻣﺘﺤﺮﻛﺔ.ﻋﺎﺋﻠﻲ` | multi-genre Arabic/Persian string |
| `ﻛﻮﻣﻴﺪﻱ طبخ` | multi-genre Arabic/Persian string |
| `الدوافع والظروف` | multi-genre Arabic/Persian string |
| `بودكاست حواري` | multi-genre Arabic/Persian string |
| `كوميديا صانعي المحتوى` | multi-genre Arabic/Persian string |
| `في حارة` | multi-genre Arabic/Persian string |
| `ﻛﻮﻣﻴﺪﻱ ﺭﺳﻮﻡ ﻣﺘﺤﺮﻛﺔ` | multi-genre Arabic/Persian string |
| `Paradokument` | Polish scripted-docudrama format — distinct, no canonical |
| `Sitcom` | sitcom — comedy sub-format (fold to Comedy? owner Q) |
| `Kändisar` | Swedish 'celebrities' — no canonical |
| `Podróżniczy` | Polish 'travel' — no canonical |
| `Popkultur` | German 'pop culture' — not a standard genre |
| `Psychologiczny` | Polish 'psychological' — no canonical |
| `Biograf` | Swedish/Danish 'cinema' — NOT biography |
| `Ciencia tecnología` | Spanish 'science & technology' — no canonical |
| `Kabaret` | Polish 'cabaret' — distinct, no canonical |
| `Kabarety` | Polish 'cabaret' (pl.) — distinct, no canonical |
| `Kort` | Swedish/Danish 'short' — format, no canonical |
| `Kostiumowy` | Polish 'costume/period' — no canonical |
| `Matlagning` | Swedish 'cooking' — no canonical |
| `Melodramat` | Polish 'melodrama' — distinct, no canonical |
| `Metamorfoza` | Polish 'makeover' — no canonical |
| `Mockumentary` | distinct format — no canonical |
| `Motoryzacyjny Show` | Polish 'automotive show' — no canonical |
| `Musical` | musical — distinct genre, no canonical |
| `Naturaleza` | Spanish 'nature' — no canonical |
| `Randkowy Show` | Polish 'dating show' — no canonical |
| `Relax` | 'Relax' — not a standard genre |
| `Stand Up` | stand-up — comedy sub-format (fold to Comedy? owner Q) |
| `Szpiegowski` | Polish 'spy' — no canonical |
| `كرة القدم` | Arabic 'football/soccer' — specific sport (fold to Sports? owner Q) |
| `festivals` | 'festivals', not a standard genre |
| `ترفيهي` | single-token Arabic/Persian, uncertain translation |
| `روایت` | single-token Arabic/Persian, uncertain translation |
| `إجتماعي` | single-token Arabic/Persian, uncertain translation |
| `ﺑﺮﻧﺎﻣﺞ` | single-token Arabic/Persian, uncertain translation |
| `تشويق` | single-token Arabic/Persian, uncertain translation |
| `ديني` | single-token Arabic/Persian, uncertain translation |
| `اجتماعي` | single-token Arabic/Persian, uncertain translation |
| `مُسابقات` | single-token Arabic/Persian, uncertain translation |
| `احتماعی` | single-token Arabic/Persian, uncertain translation |
| `استعدادیابی` | single-token Arabic/Persian, uncertain translation |
| `استعراضي` | single-token Arabic/Persian, uncertain translation |
| `البودكاست` | single-token Arabic/Persian, uncertain translation |
| `بودكاست` | single-token Arabic/Persian, uncertain translation |
| `تحقيق` | single-token Arabic/Persian, uncertain translation |
| `عروسکی` | single-token Arabic/Persian, uncertain translation |
| `مذهبی` | single-token Arabic/Persian, uncertain translation |
| `موزیکال` | single-token Arabic/Persian, uncertain translation |
| `ﺧﻴﺎﻝ` | single-token Arabic/Persian, uncertain translation |
| `ﻭﺇﺛﺎﺭ` | single-token Arabic/Persian, uncertain translation |
| `ﻭﺇﺛﺎﺭﺓ` | single-token Arabic/Persian, uncertain translation |
| `سيتكوم` | single-token Arabic/Persian, uncertain translation |
| `طبخ` | single-token Arabic/Persian, uncertain translation |
| `مسلسل` | single-token Arabic/Persian, uncertain translation |
| `Social` | 'Social' standalone — ambiguous (verified: IR social-drama channels; see conflict flag) |
| `Show` | bare 'Show' — ambiguous (existing code deliberately does NOT fold it) |
| `Rozrywka` | Polish 'entertainment' — ambiguous |
| `Pembe Dizi` | Turkish romantic-soap series — ambiguous (soap vs romance; owner Q) |
| `Bio` | 'Bio' — ambiguous ('biography' vs 'cinema') |
| `Comedy \| Drama \| Romance` | distinct/ambiguous label, no confident canonical |
| `Dramat historyczny` | distinct/ambiguous label, no confident canonical |
| `Fabuła` | Polish 'feature/fiction' — ambiguous |
| `LOVE` | 'Love' category — ambiguous (could be Romance; not confidently a genre) |
| `Nöje` | Swedish 'entertainment/variety' — ambiguous |
| `Obyczajowy` | Polish 'social/customs drama' — ambiguous |
| `Pioseneki` | distinct/ambiguous label, no confident canonical |
| `Rozrywkowy` | Polish 'entertaining' — ambiguous |
| `chasse` | distinct/ambiguous label, no confident canonical |
| `Mini-série` | distinct/ambiguous label, no confident canonical |
| `GAİN` | Turkish streaming-platform brand (verified: \ |
| `broadcast` | generic 'broadcast', not a genre |
| `Aventuras. Acción \| Manga. Live-Action. Años 1900 (circa)` | junk multi-descriptor string |
| `Hindi season 14` | season descriptor, not a genre |
| `Oudercontact in het tweede leerjaar: voor de meester de lastigste avond van het jaar.` | leaked Dutch episode description, not a genre |
| `Silent` | silent-film descriptor — no canonical |
| `Silent Movies` | silent-film descriptor — no canonical |
| `Ambulance` | show title, not a genre |
| `ook bekend als GTST` | Dutch 'also known as GTST', junk |
| `تدور أحداث المسلسل حول عائلة مصرية تواجه رياح التغيير العاتية التي تعصف بالمجتمع. من خلال تفاصيل يومية بسيطة، يفتح العمل ملفات شائكة تمس كل بيت؛ من صراع الضمير أمام إغراءات الرشوة، إلى مرارة الطلاق وأثره على الأبناء، وضياع حق الجار في زمن الانعزال الرقمي،` | leaked show synopsis, not a genre |
| `D` | single-letter junk |
| `null` | literal 'null', junk |
| `drama - action` | Action+Drama compound — single spelling; would need own canonical |
| `Teen Drama` | Teen+Drama compound (audience-qualified) — single spelling; would need own canonical |
| `Dokument - Sportowy` | Polish 'documentary-sport' compound — no canonical |
| `Family Drama` | Family+Drama compound — single spelling; would need own canonical |
| `Naturaleza Documental` | Spanish 'nature documentary' compound — no canonical |
| `Thriller. Intriga` | Spanish Thriller+Intrigue compound — no canonical |
| `komedija sitkom` | Croatian 'comedy sitcom' compound — no canonical |
| `romantična komedija` | Croatian 'romantic comedy' compound — single spelling; would need own canonical |
| `triler drama` | Croatian 'thriller drama' compound — no canonical |
| `DRAMA.FAMILY` | Drama+Family compound — single spelling; would need own canonical |
| `Horror · Thriller` | Horror+Thriller compound — single spelling; would need own canonical |
| `variety` | was mis-mapped to Talk Show — Variety ≠ Talk Show (#153 fix) |
| `underhållning` | Swedish 'entertainment'; was mis-mapped to Talk Show (#153 fix) |
| `اجتماعی` | Persian 'social'; was a concept-guess mapped to Drama — now raw (#153 fix) |

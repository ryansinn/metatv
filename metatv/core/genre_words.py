"""Genre WORDS in other languages, for strings no exact-match table can hold.

``filter_utils._GENRE_NORM`` maps whole strings ("دراما" -> Drama). Providers
send combinations instead: "Comedy طنز اجتماعی", "طبيعة ثقافي علوم وثائقي
رومانسي دراما", "Drama درام | اجتماعی" — and the same word in Arabic
presentation forms ("ﺩﺭاﻣﺎ") that compare unequal to the plain letters. Each
distinct string became its own genre tag, so the filter list carried hundreds
of rows for about thirty genres (owner, 2026-10-20: "dozens of arabic drama and
comedy").

:func:`resolve_genres` (below) folds a string with
:func:`fold_text` and looks up each word here. Values are canonical genres
(``filter_utils.KNOWN_GENRES``) only — a word with no honest canonical genre
("programme", "Iranian series") is simply absent, and a string with no known
word passes through unchanged (capture generously).

This is also the natural home for showing genres in the user's language later:
the canonical value is the identity, and a translation is a display concern.
"""
from __future__ import annotations

import re
import unicodedata

#: Arabic diacritics (harakat), tatweel and zero-width marks: invisible in
#: display, different in comparison.
_STRIP_RE = re.compile("[ً-ٰٟـ​-‏‪-‮⁦-⁩]")

#: Word separators seen in provider genre strings: space, Arabic comma, pipe,
#: middle dot, slash, backslash, ampersand, plus ASCII punctuation.
WORD_SPLIT_RE = re.compile(r"[\s،؛|·/\\&,;:.()\[\]\-]+")


#: Letters Persian and Arabic write differently for the same sound: Persian
#: yeh/keheh and Arabic alef maksura compare unequal to Arabic yeh/kaf.
_LETTER_FOLD = str.maketrans({"\u06CC": "\u064A", "\u0649": "\u064A", "\u06A9": "\u0643"})


def fold_text(s: str) -> str:
    """Comparable form: NFKC (presentation forms -> letters), marks stripped,
    Persian/Arabic letter variants unified, lower case."""
    s = _STRIP_RE.sub("", unicodedata.normalize("NFKC", s)).translate(_LETTER_FOLD)
    return s.strip().lower()


#: Two-word phrases, checked before single words.
GENRE_PHRASES: dict[str, str] = {
    "خيال علمي": "Science Fiction",
    "رسوم متحركة": "Animation",
    "تلفزيون الواقع": "Reality",
    "توك شو": "Talk Show",
    "سيرة ذاتية": "Biography",
    "علمی تخیلی": "Science Fiction",
    "تاک شو": "Talk Show",
    "هیجان انگیز": "Thriller",
}

#: Single words. Keys are :func:`fold_text` forms. Only words whose genre is
#: obvious (owner, 2026-10-20: "error on the side of caution not merging or
#: blending anything questionable") — so "social", "cultural", "entertainment"
#: are deliberately absent.
GENRE_WORDS: dict[str, str] = {
    # ── Arabic ────────────────────────────────────────────────────────────
    "دراما": "Drama", "الدراما": "Drama", "درامي": "Drama", "درامية": "Drama",
    "كوميدي": "Comedy", "كوميديا": "Comedy", "كوميدية": "Comedy", "الكوميديا": "Comedy",
    "رومانسي": "Romance", "رومانسية": "Romance", "رومانسيه": "Romance",
    "وثائقي": "Documentary", "وثائقية": "Documentary", "وثائقيات": "Documentary",
    "رعب": "Horror", "اكشن": "Action", "أكشن": "Action",
    "اثارة": "Thriller", "إثارة": "Thriller", "تشويق": "Thriller",
    "جريمة": "Crime", "جريمه": "Crime", "غموض": "Mystery",
    "تاريخي": "History", "تاريخية": "History", "حرب": "War", "حربي": "War",
    "عائلي": "Family", "عائلية": "Family", "اطفال": "Kids", "أطفال": "Kids",
    "انمي": "Anime", "أنمي": "Anime", "مغامرة": "Adventure", "مغامرات": "Adventure",
    "فانتازيا": "Fantasy", "خيال": "Fantasy",
    "موسيقي": "Music", "موسيقى": "Music", "غنائي": "Music", "غنائية": "Music",
    "رياضي": "Sports", "رياضة": "Sports", "رياضية": "Sports",
    "سياسي": "Politics", "سياسية": "Politics",
    "إخباري": "News", "اخباري": "News", "أخبار": "News", "اخبار": "News",
    "حواري": "Talk Show", "واقع": "Reality",
    "مسابقات": "Game Show", "ويسترن": "Western",
    # ── Persian ───────────────────────────────────────────────────────────
    "درام": "Drama",
    "کمدی": "Comedy", "طنز": "Comedy",
    "خانوادگی": "Family", "عاشقانه": "Romance", "جنایی": "Crime",
    "ترسناک": "Horror", "اکشن": "Action", "هیجانی": "Thriller", "معمایی": "Mystery",
    "تاریخی": "History", "جنگی": "War", "مستند": "Documentary",
    "انیمیشن": "Animation", "فانتزی": "Fantasy",
    "ماجراجویی": "Adventure", "موزیکال": "Music", "ورزشی": "Sports",
    "سیاسی": "Politics", "کودک": "Kids", "کودکان": "Kids",
    # R1 (owner-approved 2026-10-20): Arabic/Persian TV calls a family-and-
    # society drama series "social"; "police" is a crime series.
    "اجتماعي": "Drama", "اجتماعية": "Drama", "إجتماعي": "Drama", "جتماعي": "Drama",
    "احتماعي": "Drama", "ملودرام": "Drama", "social": "Drama", "پلیسی": "Crime",
    "انيميشن": "Animation", "ریلیتی": "Reality",
    # ── European and English words (single words of compound strings) ────
    "sitcom": "Comedy", "draama": "Drama", "melodramat": "Drama",
    "rikos": "Crime", "biograf": "Biography", "dokument": "Documentary", "sportowy": "Sports",
    "historyczny": "History",
    "underhållning": "Entertainment", "nöje": "Entertainment", "rozrywka": "Entertainment",
    "rozrywkowy": "Entertainment", "popkultur": "Talk Show", "kändisar": "Talk Show",
}

#: Whole strings approved one by one (owner, 2026-10-20, "Unclear Genre Tags"
#: R2): translations a word table cannot express — phrases, or one string
#: naming two genres.
GENRE_STRINGS: dict[str, tuple[str, ...]] = {
    "teen drama": ("Drama",), "psychologiczny": ("Drama",), "obyczajowy": ("Drama",),
    "urdu drama": ("Drama",), "kostiumowy": ("Drama", "History"),
    "kriminalare": ("Crime",), "szpiegowski": ("Thriller",),
    "thriller. intriga": ("Thriller",), "وإثار": ("Thriller",),
    "nachrichten": ("News",), "nyhed": ("News",), "animering": ("Animation",),
    "sci-fi och fantasy": ("Sci-Fi & Fantasy",),
    "action og eventyr": ("Action & Adventure",), "spielshow": ("Game Show",),
    "stand up": ("Stand-Up Comedy",), "kabaret": ("Comedy",), "kabarety": ("Comedy",),
    "komedija sitkom": ("Comedy",), "سيتكوم": ("Comedy",), "mockumentary": ("Comedy",),
    "musical": ("Music",), "pioseneki": ("Music",), "كرة القدم": ("Sports",),
    "دفاع مقدس": ("War",), "عروسكي": ("Kids",), "نمايش عروسكي": ("Kids",),
    "naturaleza": ("Documentary",), "naturaleza documental": ("Documentary",),
    "paradokument": ("Reality",), "tosi-tv": ("Reality",), "metamorfoza": ("Reality",),
    "randkowy show": ("Reality",), "استعداديابي": ("Reality",),
    "مسابقه ، رئاليتي شو": ("Game Show", "Reality"),
    "pembe dizi": ("Soap Opera", "Romance"), "love": ("Romance",),
    "show": (), "bio": ("Biography",),          # bare "Show": a format word
    # R3 (2026-10-20): broadcaster "entertainment" labels -> Entertainment;
    # pop culture / celebrities are celebrity talk shows.
    "games سرگرمی": ("Entertainment",),
}

#: Values a provider put in its genre field that are not genres (R5): format
#: words, episode labels, descriptions. They resolve to NO genre.
NOT_GENRES: frozenset[str] = frozenset({
    "broadcast", "film", "mini-série", "مسلسل", "مسلسل تلفزيوني تركي", "kort",
    "hindi season 14", "ook bekend als gtst", "الدوافع والظروف", "في حارة",
    "صانعي المحتوى",
})

#: A streaming service a provider wrote into its genre field (R5).
GENRE_FIELD_PLATFORMS: dict[str, str] = {"gain": "GAİN"}

#: A "genre" this many words long with no genre word in it is a description.
DESCRIPTION_MIN_WORDS = 6

# Keys are compared in folded form, so fold them once here: an entry typed
# with a Persian yeh still matches a string written with an Arabic one.
GENRE_WORDS = {fold_text(k): v for k, v in GENRE_WORDS.items()}
GENRE_PHRASES = {fold_text(k): v for k, v in GENRE_PHRASES.items()}
GENRE_STRINGS = {fold_text(k): v for k, v in GENRE_STRINGS.items()}
NOT_GENRES = frozenset(fold_text(k) for k in NOT_GENRES)


def platform_named_as_genre(segment: str) -> str | None:
    """The platform a genre field actually names ("GAİN"), or None."""
    return GENRE_FIELD_PLATFORMS.get(fold_text(segment).replace("i̇", "i"))


def words_to_genres(folded: str) -> list[str]:
    """Canonical genres named by the words of an already-folded string, in order."""
    words = [w for w in WORD_SPLIT_RE.split(folded) if w]
    out: list[str] = []
    i = 0
    while i < len(words):
        pair = f"{words[i]} {words[i + 1]}" if i + 1 < len(words) else ""
        if pair and pair in GENRE_PHRASES:
            out.append(GENRE_PHRASES[pair])
            i += 2
            continue
        word = words[i]
        genre = GENRE_WORDS.get(word)
        if genre is None and word.startswith("و") and len(word) > 2:
            genre = GENRE_WORDS.get(word[1:])        # "و" = "and", written joined
        if genre is not None:
            out.append(genre)
        i += 1
    return out


def resolve_genres(segment: str) -> list[str]:
    """One raw genre segment -> its canonical genre(s). The ingestion resolver.

    Whole-string match first (:func:`normalize_genre`, after folding Arabic
    presentation forms and marks). A string that is not itself a known genre
    is then read word by word (this module's word tables), so "Comedy طنز
    اجتماعی" yields Comedy and Drama and "Comedy | Drama | Romance" yields
    three, instead of each becoming a genre of its own. Latin text folds only
    when every word is a genre. A string with no known word passes through
    unchanged (capture generously) — except an approved not-a-genre value, a
    platform name, or a six-plus-word description, which resolve to none.
    """
    from metatv.core.filter_utils import (_GENRE_NORM, _KNOWN_GENRES_LOWER, html,
                                          normalize_genre)

    direct = normalize_genre(segment)
    if direct.lower() in _KNOWN_GENRES_LOWER:
        return [_KNOWN_GENRES_LOWER[direct.lower()]]
    folded = fold_text(html.unescape(segment))
    if direct == "" or _GENRE_NORM.get(folded) == "":
        return []          # a format word ("TV programme", "برنامج"): no genre
    canon = _GENRE_NORM.get(folded) or _KNOWN_GENRES_LOWER.get(folded)
    if canon:
        return [canon]
    if folded in GENRE_STRINGS:
        return list(GENRE_STRINGS[folded])
    if folded in NOT_GENRES or platform_named_as_genre(segment):
        return []
    words = [w for w in WORD_SPLIT_RE.split(folded) if w]
    found: list[str] = []
    for word in words:                                # any language, in order
        hit = (_GENRE_NORM.get(word) or _KNOWN_GENRES_LOWER.get(word)
               or GENRE_WORDS.get(word))
        if hit:
            found.append(hit)
    if not found and len(words) >= DESCRIPTION_MIN_WORDS and not words_to_genres(folded):
        return []          # a synopsis in the genre field, not a genre
    if segment.isascii() and len(found) < len(words):
        # Latin text folds only when EVERY word is a genre ("Comedy | Drama |
        # Romance"); "Teen Drama" or "Action og eventyr" stay as they are.
        return [direct]
    found += words_to_genres(folded)
    seen: set[str] = set()
    out = [g for g in found if not (g in seen or seen.add(g))]
    return out or [direct]

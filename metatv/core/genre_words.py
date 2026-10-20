"""Genre WORDS in other languages, for strings no exact-match table can hold.

``filter_utils._GENRE_NORM`` maps whole strings ("دراما" -> Drama). Providers
send combinations instead: "Comedy طنز اجتماعی", "طبيعة ثقافي علوم وثائقي
رومانسي دراما", "Drama درام | اجتماعی" — and the same word in Arabic
presentation forms ("ﺩﺭاﻣﺎ") that compare unequal to the plain letters. Each
distinct string became its own genre tag, so the filter list carried hundreds
of rows for about thirty genres (owner, 2026-10-20: "dozens of arabic drama and
comedy").

:func:`metatv.core.filter_utils.resolve_genres` folds a string with
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
    "انيميشن": "Animation", "ریلیتی": "Reality",
    # ── European and English words (single words of compound strings) ──── "sitcom": "Comedy", "draama": "Drama", "melodramat": "Drama",
    "rikos": "Crime", "biograf": "Biography", "dokument": "Documentary", "sportowy": "Sports",
    "historyczny": "History",
}

# Keys are compared in folded form, so fold them once here: an entry typed
# with a Persian yeh still matches a string written with an Arabic one.
GENRE_WORDS = {fold_text(k): v for k, v in GENRE_WORDS.items()}
GENRE_PHRASES = {fold_text(k): v for k, v in GENRE_PHRASES.items()}


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

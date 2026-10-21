"""Deterministic Persian text helpers for catalog search.

The functions in this module only prepare search input. They never mutate
stored service names, descriptions, or patient messages.
"""

from __future__ import annotations

import re
import unicodedata

# Arabic/Persian forms that are commonly confused in user input.
_CHAR_TRANSLATION = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ؤ": "و",
        "ئ": "ی",
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ۀ": "ه",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)

_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_PUNCTUATION_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACES_RE = re.compile(r"\s+")

# Generic words that do not distinguish one dental service from another.
STOPWORDS: frozenset[str] = frozenset(
    {
        "و",
        "يا",
        "یا",
        "از",
        "به",
        "برای",
        "با",
        "در",
        "که",
        "این",
        "آن",
        "است",
        "هست",
        "می",
        "را",
        "رو",
        "هم",
        "تا",
        "یک",
        "چه",
        "کدام",
        "کدامیک",
        "لطفا",
        "سلام",
        "نزدیک",
        "نزدیکتر",
        "نزدیکترین",
        "ترین",
        "وقت",
        "نوبت",
        "دکتر",
        "پزشک",
        "خدمت",
        "خدمات",
        "مطب",
        "دنبال",
        "میخوام",
        "میخواهم",
        "خواستم",
        "باید",
        "بده",
        "پیدا",
        "کن",
        "کنم",
        "کنید",
        "مناسب",
        "هرچی",
        "شود",
        "کردن",
        "دارید",
        "دارد",
        "دارم",
        "داره",
        "ندارم",
        "میخوای",
        "میخواید",
        "میخواستم",
        "میخوا",
        "بگیرم",
        "بگیرید",
        "بدید",
        "بدهید",
        "کنه",
        "کرده",
        "شده",
        "شدم",
        "هستش",
        "چیه",
        "چطور",
        "کجا",
        "کی",
        "هام",
        "ها",
        "های",
        "ام",
        "ات",
        "اش",
        "مان",
        "تان",
        "شان",
    }
)

# Small, explicit domain aliases. This is lexical domain knowledge, not a
# general semantic model; extend it with tests when adding catalog concepts.
SERVICE_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "معاینه": (
        "درد",
        "بررسی",
        "پوسیدگی",
        "ورم",
        "تورم",
        "خونریزی",
        "آبسه",
        "عفونت",
        "ضربه",
        "شکستگی",
        "شکسته",
    ),
    "بررسی": (
        "درد",
        "پوسیدگی",
        "ورم",
        "تورم",
        "خونریزی",
        "آبسه",
        "عفونت",
        "ضربه",
    ),
    "ترمیم": ("پوسیدگی", "شکستگی", "شکسته", "خراب", "آبسه"),
    "پوسیدگی": ("ترمیم", "خراب"),
    "جرم": ("پلاک",),
    "پلاک": ("جرم",),
    "درد": ("معاینه", "بررسی"),
}

# These words are useful for discovery but too broad to prove relevance on
# their own when the query also contains a specific symptom.
GENERIC_SEARCH_TERMS: frozenset[str] = frozenset({"دندان"})


def normalize_persian_text(value: str | None) -> str:
    """Normalize Persian/Arabic variants and punctuation for matching."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.translate(_CHAR_TRANSLATION)
    text = _DIACRITICS_RE.sub("", text)
    # ZWNJ/ZWJ and bidi marks separate words for search purposes.
    text = text.replace("\u200c", " ").replace("\u200d", " ")
    text = re.sub(r"[\u200e\u200f\u202a-\u202e]", " ", text)
    text = text.replace("_", " ")
    text = _PUNCTUATION_RE.sub(" ", text)
    text = text.lower()
    return _SPACES_RE.sub(" ", text).strip()


def canonicalize_token(token: str) -> str:
    """Map common inflections/colloquial forms to a catalog-friendly token."""
    if not token:
        return ""
    if token.startswith(("دندون", "دندان")):
        return "دندان"
    if token.startswith("دند") and len(token) <= 6:
        return "دندان"
    if token.startswith("پوسید"):
        return "پوسیدگی"
    if token.startswith("درد"):
        return "درد"
    if token.startswith("معاین"):
        return "معاینه"
    if token.startswith("بررس"):
        return "بررسی"
    if token.startswith("ترمیم"):
        return "ترمیم"
    if token.startswith("جرم"):
        return "جرم"
    return token


def search_terms(value: str | None) -> list[str]:
    """Return unique, meaningful canonical query terms in input order."""
    terms: list[str] = []
    for raw_token in normalize_persian_text(value).split():
        token = canonicalize_token(raw_token)
        if not token or token in STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms


def is_generic_query(value: str | None) -> bool:
    """Whether a non-empty query contains only generic/stop words."""
    raw_tokens = normalize_persian_text(value).split()
    if not raw_tokens:
        return True
    return all(canonicalize_token(token) in STOPWORDS for token in raw_tokens)


def concept_aliases(tokens: set[str]) -> set[str]:
    """Return one-level domain aliases for a set of canonical tokens."""
    aliases: set[str] = set()
    for token in tokens:
        aliases.update(SERVICE_CONCEPT_ALIASES.get(token, ()))
    return aliases - tokens

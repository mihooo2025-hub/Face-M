import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Iterable

ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = ARABIC_DIACRITICS.sub("", text)
    text = text.replace("ـ", "")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.I)
    text = re.sub(r"[@#][\w\u0600-\u06FF_.-]+", " ", text)
    text = re.sub(r"[^\w\u0600-\u06FF]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().lower()


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w\u0600-\u06FF]+\b", text or "", flags=re.UNICODE))


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def url_hash(url: str) -> str:
    return hashlib.sha256((url or "").strip().encode("utf-8")).hexdigest()


def similar(a: str, b: str) -> float:
    a_n = normalize_text(a)[:700]
    b_n = normalize_text(b)[:700]
    if not a_n or not b_n:
        return 0.0
    return SequenceMatcher(None, a_n, b_n).ratio()


def contains_any(text: str, phrases: Iterable[str]) -> bool:
    n = normalize_text(text)
    return any(normalize_text(p) in n for p in phrases)

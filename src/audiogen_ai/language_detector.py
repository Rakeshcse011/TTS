"""Conservative script-based language detection for Hindi-English text."""

from __future__ import annotations

from dataclasses import dataclass
import re

_DEVANAGARI = re.compile(r"[\u0900-\u097f]")
_LATIN = re.compile(r"[A-Za-z]")
_ROMAN_HINDI_WORDS = {
    "aaj",
    "aur",
    "bahut",
    "hai",
    "hain",
    "hum",
    "ka",
    "kar",
    "ke",
    "ki",
    "kya",
    "mein",
    "mera",
    "nahi",
    "seekhenge",
    "se",
    "yeh",
}


@dataclass(frozen=True, slots=True)
class LanguageResult:
    language: str
    hindi_characters: int
    latin_characters: int
    recommendation: str


def detect_language(text: str) -> LanguageResult:
    hindi_count = len(_DEVANAGARI.findall(text))
    latin_count = len(_LATIN.findall(text))
    roman_words = set(re.findall(r"[a-z]+", text.casefold()))
    roman_hindi_count = len(roman_words & _ROMAN_HINDI_WORDS)
    if not hindi_count and not latin_count:
        language = "unknown"
    elif hindi_count and latin_count:
        language = "mixed"
    elif roman_hindi_count >= 2 and len(roman_words) > roman_hindi_count:
        language = "mixed"
    elif hindi_count or roman_hindi_count >= 2:
        language = "hindi"
    else:
        language = "english"

    recommendation = (
        "hi-IN-MadhurNeural"
        if hindi_count > 0 or roman_hindi_count >= 2
        else "en-IN-PrabhatNeural"
    )
    return LanguageResult(language, hindi_count, latin_count, recommendation)

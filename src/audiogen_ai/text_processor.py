"""Conservative deterministic normalization before speech synthesis."""

from __future__ import annotations

import re
from calendar import month_name
from datetime import date

from audiogen_ai.pronunciation_engine import apply_pronunciations

_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_CURRENCY = re.compile(r"₹\s*([\d,]+)(?:\.(\d{1,2}))?")
_MATH = re.compile(r"(?<!\w)[A-Za-z0-9]+(?:\s*[+=×÷]\s*[A-Za-z0-9]+)+(?!\w)")
_WATER = re.compile(r"\bH₂O\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_INDIAN_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTHS = "|".join(month_name[index] for index in range(1, 13))
_MONTH_DATE = re.compile(
    rf"\b({_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_DAY_MONTH_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})[,]?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})(\s*[ap]\.?m\.?)?\b", re.IGNORECASE)
_MEASUREMENT = re.compile(
    r"(?<!\w)(\d+(?:\.\d+)?)\s*(km/h|kg|km|cm|mm|°c|°f|ml|m|g|l|%)(?![A-Za-z])",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![\w.])-?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w.])")
_WORD_BOUNDARY = re.compile(r"\bAI\b")
_DIGIT_WORDS = {
    "km/h": "kilometers per hour",
    "kg": "kilograms",
    "km": "kilometers",
    "cm": "centimeters",
    "mm": "millimeters",
    "°c": "degrees Celsius",
    "°f": "degrees Fahrenheit",
    "ml": "milliliters",
    "m": "meters",
    "g": "grams",
    "l": "liters",
    "%": "percent",
}
_TITLE = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof)\.(?=\s+[A-Z\u0900-\u097f])")
_ETC = re.compile(r"\betc\.(?=\s|$)", re.IGNORECASE)
_SPACES = re.compile(r"[ \t]+")

_TITLE_EXPANSIONS = {
    "Dr": "Doctor",
    "Mr": "Mister",
    "Mrs": "Misses",
    "Ms": "Miss",
    "Prof": "Professor",
}
_NUMBER_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)


def _under_thousand(number: int) -> str:
    words: list[str] = []
    if number >= 100:
        words.extend((_NUMBER_WORDS[number // 100], "hundred"))
        number %= 100
    if number >= 20:
        words.append(_TENS[number // 10])
        number %= 10
    if number:
        words.append(_NUMBER_WORDS[number])
    return " ".join(words)


def number_to_words(value: int) -> str:
    if value < 0:
        return f"minus {number_to_words(-value)}"
    if value < 20:
        return _NUMBER_WORDS[value]
    if value < 100:
        return _under_thousand(value)
    if value < 1_000:
        return _under_thousand(value)
    groups: list[tuple[int, str]] = [
        (10**7, "crore"),
        (10**5, "lakh"),
        (1_000, "thousand"),
    ]
    words: list[str] = []
    remainder = value
    for divisor, label in groups:
        if remainder >= divisor:
            count, remainder = divmod(remainder, divisor)
            words.extend((number_to_words(count), label))
    if remainder:
        words.append(_under_thousand(remainder))
    return " ".join(words)


def _expand_currency(match: re.Match[str]) -> str:
    amount = int(match.group(1).replace(",", ""))
    result = f"{number_to_words(amount)} rupees"
    if match.group(2):
        paise = int(match.group(2).ljust(2, "0"))
        if paise:
            result += f" and {number_to_words(paise)} paise"
    return result


def _expand_math(match: re.Match[str]) -> str:
    operators = {"+": "plus", "=": "equals", "×": "times", "÷": "divided by"}
    tokens = re.split(r"\s*([+=×÷])\s*", match.group(0))
    return " ".join(
        operators.get(token, token) for token in tokens if token
    )


def _spoken_number(value: str) -> str:
    negative = value.startswith("-")
    if negative:
        value = value[1:]
    value = value.replace(",", "")
    if "." in value:
        integer, fraction = value.split(".", maxsplit=1)
        spoken = (
            f"{number_to_words(int(integer))} point "
            f"{' '.join(_NUMBER_WORDS[int(digit)] for digit in fraction)}"
        )
    else:
        spoken = number_to_words(int(value))
    return f"minus {spoken}" if negative else spoken


def _expand_measurement(match: re.Match[str]) -> str:
    return f"{_spoken_number(match.group(1))} {_DIGIT_WORDS[match.group(2).lower()]}"


def _spoken_date(year: int, month: int, day: int, fallback: str) -> str:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return fallback
    return f"{number_to_words(parsed.day)} {month_name[parsed.month]} {number_to_words(parsed.year)}"


def _expand_iso_date(match: re.Match[str]) -> str:
    year, month, day = (int(value) for value in match.groups())
    return _spoken_date(year, month, day, match.group(0))


def _expand_indian_date(match: re.Match[str]) -> str:
    day, month, year = (int(value) for value in match.groups())
    return _spoken_date(year, month, day, match.group(0))


def _month_number(month: str) -> int:
    return next(
        index for index in range(1, 13) if month_name[index].casefold() == month.casefold()
    )


def _expand_month_date(match: re.Match[str]) -> str:
    month, day, year = match.groups()
    return _spoken_date(int(year), _month_number(month), int(day), match.group(0))


def _expand_day_month_date(match: re.Match[str]) -> str:
    day, month, year = match.groups()
    return _spoken_date(int(year), _month_number(month), int(day), match.group(0))


def _expand_time(match: re.Match[str]) -> str:
    hour, minute = int(match.group(1)), int(match.group(2))
    suffix = (match.group(3) or "").replace(".", "").strip().lower()
    if hour > 23 or minute > 59:
        return match.group(0)
    hour_word = number_to_words(hour)
    if minute == 0:
        spoken = f"{hour_word} o'clock"
    elif minute < 10:
        spoken = f"{hour_word} oh {number_to_words(minute)}"
    else:
        spoken = f"{hour_word} {number_to_words(minute)}"
    return f"{spoken} {suffix}".strip()


def prepare_text(
    text: str,
    pronunciations: dict[str, str] | None = None,
    url_policy: str = "read",
) -> str:
    """Apply meaning-preserving, documented speech substitutions."""
    if url_policy not in {"read", "omit"}:
        raise ValueError("URL policy must be 'read' or 'omit'.")
    if url_policy == "omit":
        text = _MARKDOWN_LINK.sub(lambda match: match.group(1), text)
        text = _URL.sub("", text)
    else:
        text = _MARKDOWN_LINK.sub(
            lambda match: f"{match.group(1)}, {match.group(2).replace('://', ' ')}",
            text,
        )
        text = _URL.sub(lambda match: match.group(0).replace("://", " "), text)
    text = _CURRENCY.sub(_expand_currency, text)
    text = _WATER.sub("H two O", text)
    text = _MATH.sub(_expand_math, text)
    text = _ISO_DATE.sub(_expand_iso_date, text)
    text = _INDIAN_DATE.sub(_expand_indian_date, text)
    text = _MONTH_DATE.sub(_expand_month_date, text)
    text = _DAY_MONTH_DATE.sub(_expand_day_month_date, text)
    text = _TIME.sub(_expand_time, text)
    text = _MEASUREMENT.sub(_expand_measurement, text)
    text = _NUMBER.sub(
        lambda match: _spoken_number(match.group(0)),
        text,
    )
    text = _TITLE.sub(lambda match: _TITLE_EXPANSIONS[match.group(1)], text)
    text = _ETC.sub("et cetera", text)
    text = apply_pronunciations(text, pronunciations or {})
    if not any(term.casefold() == "ai" for term in (pronunciations or {})):
        text = _WORD_BOUNDARY.sub("A I", text)
    text = _SPACES.sub(" ", text)
    return text.strip()

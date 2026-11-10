"""Explicit, user-controlled pronunciation substitutions."""

from __future__ import annotations

import re
from collections.abc import Mapping


def apply_pronunciations(text: str, pronunciations: Mapping[str, str]) -> str:
    for term, pronunciation in sorted(pronunciations.items(), key=lambda item: -len(item[0])):
        if not term or not pronunciation:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        text = pattern.sub(lambda match: pronunciation, text)
    return text

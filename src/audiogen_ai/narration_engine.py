"""SSML construction for Azure neural narration."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re


@dataclass(frozen=True, slots=True)
class NarrationProfile:
    style: str = "Classroom Teacher"
    speed_percent: int = 100
    volume_percent: int = 100
    pitch_hz: int = 0
    sentence_pause_ms: int = 350
    paragraph_pause_ms: int = 700


_SENTENCES = re.compile(r"(?<=[.!?।])\s+")
_STYLE_DELIVERY = {
    "Classroom Teacher": (-3, 0, 100, 0),
    "Friendly Teacher": (2, 1, -150, -200),
    "Professional Narrator": (-2, 0, -150, -100),
    "Confident Presenter": (0, 1, -100, -50),
}


def delivery_adjustments(style: str) -> tuple[int, int]:
    try:
        rate_adjustment, pitch_adjustment, _, _ = _STYLE_DELIVERY[style]
    except KeyError as exc:
        raise ValueError("Choose a supported narration style.") from exc
    return rate_adjustment, pitch_adjustment


def build_ssml(text: str, voice: str, profile: NarrationProfile) -> str:
    if not text.strip():
        raise ValueError("Cannot create SSML from empty text.")
    if profile.style not in {
        "Classroom Teacher",
        "Friendly Teacher",
        "Professional Narrator",
        "Confident Presenter",
    }:
        raise ValueError("Choose a supported narration style.")
    if not 70 <= profile.speed_percent <= 130:
        raise ValueError("Speaking speed must be between 70% and 130%.")
    if not 0 <= profile.volume_percent <= 100:
        raise ValueError("Volume must be between 0% and 100%.")
    if not -50 <= profile.pitch_hz <= 50:
        raise ValueError("Pitch must be between -50 Hz and 50 Hz.")
    if not 0 <= profile.sentence_pause_ms <= 2_000:
        raise ValueError("Sentence pause must be between 0 and 2000 ms.")
    if not 0 <= profile.paragraph_pause_ms <= 5_000:
        raise ValueError("Paragraph pause must be between 0 and 5000 ms.")

    rate_adjustment, pitch_adjustment = delivery_adjustments(profile.style)
    _, _, sentence_adjustment, paragraph_adjustment = _STYLE_DELIVERY[profile.style]
    effective_rate = max(70, min(130, profile.speed_percent + rate_adjustment))
    effective_pitch = profile.pitch_hz + pitch_adjustment
    sentence_pause = max(0, min(2000, profile.sentence_pause_ms + sentence_adjustment))
    paragraph_pause = max(0, min(5000, profile.paragraph_pause_ms + paragraph_adjustment))
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        sentences = [sentence for sentence in _SENTENCES.split(paragraph.strip()) if sentence]
        if not sentences:
            continue
        spoken = "".join(
            escape(sentence)
            + (
                f'<break time="{sentence_pause}ms"/>'
                if index < len(sentences) - 1
                else ""
            )
            for index, sentence in enumerate(sentences)
        )
        paragraphs.append(spoken)
    body = (
        f'<break time="{paragraph_pause}ms"/>'.join(paragraphs)
        if paragraphs
        else escape(text)
    )
    language = "-".join(voice.split("-")[:2])
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{escape(language, quote=True)}">'
        f'<voice name="{escape(voice, quote=True)}">'
        f'<prosody rate="{effective_rate}%" '
        f'volume="{profile.volume_percent}%" pitch="{effective_pitch:+d}Hz">'
        f"{body}</prosody></voice></speak>"
    )

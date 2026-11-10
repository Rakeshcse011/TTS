"""Input validation and safe text chunking."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath, PureWindowsPath

from audiogen_ai.config import MAX_CHUNK_CHARS, MAX_TEXT_CHARS, VOICES

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?।])\s+")


def validate_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(text, str):
        raise ValueError("Text must be a string.")
    text = _CONTROL_CHARS.sub("", text).strip()
    if not text:
        raise ValueError("Enter some text before generating audio.")
    if len(text) > max_chars:
        raise ValueError(f"Text is too long. The limit is {max_chars:,} characters.")
    return text


def validate_voice(voice: str) -> str:
    if voice not in VOICES:
        raise ValueError("Choose a supported Hindi or English voice.")
    return voice


def validate_adjustment(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not -50 <= value <= 50:
        raise ValueError(f"{name} must be a whole number between -50 and 50.")
    return value


def validate_output_format(output_format: str) -> str:
    if output_format not in {"mp3", "wav"}:
        raise ValueError("Output format must be MP3 or WAV.")
    return output_format


def sanitize_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(filename))
    name = PureWindowsPath(normalized).name
    name = PurePosixPath(name).name
    name = name.rsplit(".", 1)[0] if "." in name else name
    safe = re.sub(r"[^\w -]", "", name, flags=re.UNICODE)
    safe = re.sub(r"[\s-]+", "-", safe).strip("-_")[:64]
    return safe or "speech"


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    if max_chars < 1:
        raise ValueError("Chunk size must be positive.")
    chunks: list[str] = []
    current = ""

    def append_piece(piece: str) -> None:
        nonlocal current
        piece = piece.strip()
        while piece:
            available = max_chars - len(current)
            if len(piece) <= available:
                current = f"{current} {piece}".strip()
                return
            boundary = piece.rfind(" ", 0, available + 1)
            if boundary <= 0:
                boundary = available
            segment, piece = piece[:boundary].strip(), piece[boundary:].strip()
            if segment:
                current = f"{current} {segment}".strip()
            if current:
                chunks.append(current)
                current = ""

    for paragraph in text.splitlines():
        if not paragraph.strip():
            if current:
                chunks.append(current)
                current = ""
            continue
        sentences = _SENTENCE_BOUNDARY.split(paragraph.strip())
        for sentence in sentences:
            if len(sentence) > max_chars:
                append_piece(sentence)
            elif current and len(current) + len(sentence) + 1 > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks

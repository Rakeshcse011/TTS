"""Persistent, explicitly finalized voice calibration profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json

from audiogen_ai.config import VOICES


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    name: str = "Indian Teacher"
    provider: str = "local"
    voice: str = "local:en"
    language: str = "Auto detect"
    accent: str = "International"
    style: str = "Classroom Teacher"
    speed_percent: int = 100
    volume_percent: int = 100
    pitch_hz: int = 0
    sentence_pause_ms: int = 350
    paragraph_pause_ms: int = 700
    sample_rate: int = 22_050
    normalize_audio: bool = False
    url_policy: str = "read"
    output_format: str = "wav"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, serialized: str) -> VoiceProfile:
        values = json.loads(serialized)
        if not isinstance(values, dict):
            raise ValueError("Voice profile must be a JSON object.")
        allowed = set(cls.__dataclass_fields__)
        if set(values) - allowed:
            raise ValueError("Voice profile contains unknown settings.")
        profile = cls(**values)
        if profile.provider not in {"local", "azure", "edge"}:
            raise ValueError("Voice profile has an unsupported provider.")
        if profile.voice not in VOICES or VOICES[profile.voice].provider != profile.provider:
            raise ValueError("Voice profile has an unsupported voice for its provider.")
        if profile.style not in {
            "Classroom Teacher",
            "Friendly Teacher",
            "Professional Narrator",
            "Confident Presenter",
        }:
            raise ValueError("Voice profile has an unsupported narration style.")
        if not 70 <= profile.speed_percent <= 130:
            raise ValueError("Voice profile speed is out of range.")
        if not 0 <= profile.volume_percent <= 100:
            raise ValueError("Voice profile volume is out of range.")
        if not -50 <= profile.pitch_hz <= 50:
            raise ValueError("Voice profile pitch is out of range.")
        if not 0 <= profile.sentence_pause_ms <= 2_000:
            raise ValueError("Voice profile sentence pause is out of range.")
        if not 0 <= profile.paragraph_pause_ms <= 5_000:
            raise ValueError("Voice profile paragraph pause is out of range.")
        if profile.sample_rate not in {16_000, 22_050, 24_000, 48_000}:
            raise ValueError("Voice profile sample rate is unsupported.")
        if profile.url_policy not in {"read", "omit"}:
            raise ValueError("Voice profile URL policy is unsupported.")
        if profile.output_format not in {"mp3", "wav"}:
            raise ValueError("Voice profile output format is unsupported.")
        return profile


PREVIEW_TEXT = (
    "Welcome to today's lesson. We will explore one clear idea, "
    "connect it to what you already know, and practise it together."
)

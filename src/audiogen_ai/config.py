"""Application settings and supported neural voices."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(frozen=True, slots=True)
class Voice:
    name: str
    language: str
    language_code: str
    gender: str
    provider: str = "edge"
    accent: str = "International"
    synthesis_id: str | None = None


VOICES: dict[str, Voice] = {
    "local:en": Voice(
        "English (eSpeak NG)", "English", "en", "Neutral", "local", "International", "en"
    ),
    "local:hi": Voice("Hindi (eSpeak NG)", "Hindi", "hi", "Neutral", "local", "Indian", "hi"),
    "en-IN-PrabhatNeural": Voice(
        "Prabhat", "Indian English", "en-IN", "Male", "azure", "Indian"
    ),
    "hi-IN-MadhurNeural": Voice("Madhur", "Hindi", "hi-IN", "Male", "azure", "Indian"),
    "hi-IN-SwaraNeural": Voice("Swara", "Hindi", "hi-IN", "Female", "azure", "Indian"),
    "en-IN-NeerjaNeural": Voice(
        "Neerja", "Indian English", "en-IN", "Female", "azure", "Indian"
    ),
    "edge:en-IN-PrabhatNeural": Voice(
        "Prabhat (Edge)", "Indian English", "en-IN", "Male", "edge", "Indian", "en-IN-PrabhatNeural"
    ),
    "edge:hi-IN-SwaraNeural": Voice(
        "Swara (Edge)", "Hindi", "hi-IN", "Female", "edge", "Indian", "hi-IN-SwaraNeural"
    ),
    "edge:hi-IN-MadhurNeural": Voice(
        "Madhur (Edge)", "Hindi", "hi-IN", "Male", "edge", "Indian", "hi-IN-MadhurNeural"
    ),
    "en-US-AvaNeural": Voice("Ava", "English (US)", "en-US", "Female"),
    "en-US-AndrewNeural": Voice("Andrew", "English (US)", "en-US", "Male"),
    "en-GB-SoniaNeural": Voice("Sonia", "English (UK)", "en-GB", "Female"),
    "en-GB-RyanNeural": Voice("Ryan", "English (UK)", "en-GB", "Male"),
}

MAX_TEXT_CHARS = 100_000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CHUNK_CHARS = 2_800


def default_data_dir() -> Path:
    configured = os.environ.get("AUDIOGEN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "AudioGenAI"
        return Path.home() / "AppData" / "Local" / "AudioGenAI"
    return Path.home() / ".local" / "share" / "audiogen-ai"


def default_espeak_path() -> str:
    configured = os.environ.get("AUDIOGEN_ESPEAK_PATH")
    if configured:
        return configured
    discovered = shutil.which("espeak-ng")
    if discovered:
        return discovered
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        installed = program_files / "eSpeak NG" / "espeak-ng.exe"
        if installed.is_file():
            return str(installed)
    return "espeak-ng"


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    max_text_chars: int = MAX_TEXT_CHARS
    max_upload_bytes: int = MAX_UPLOAD_BYTES
    chunk_chars: int = MAX_CHUNK_CHARS
    concurrency: int = 2
    retries: int = 2
    request_timeout: float = 45.0
    api_key: str | None = None
    ffmpeg_path: str = "ffmpeg"
    azure_speech_key: str | None = None
    azure_speech_region: str | None = None
    default_provider: str = "local"
    espeak_path: str = "espeak-ng"

    @classmethod
    def from_env(cls) -> Settings:
        configured_provider = os.environ.get("AUDIOGEN_TTS_PROVIDER", "local").lower()
        return cls(
            data_dir=default_data_dir(),
            api_key=os.environ.get("AUDIOGEN_API_KEY") or None,
            ffmpeg_path=os.environ.get("AUDIOGEN_FFMPEG_PATH", "ffmpeg"),
            azure_speech_key=os.environ.get("AZURE_SPEECH_KEY") or None,
            azure_speech_region=os.environ.get("AZURE_SPEECH_REGION") or None,
            default_provider=(
                configured_provider
                if configured_provider in {"local", "azure", "edge"}
                else "local"
            ),
            espeak_path=default_espeak_path(),
        )

    @property
    def azure_configured(self) -> bool:
        return bool(self.azure_speech_key and self.azure_speech_region)

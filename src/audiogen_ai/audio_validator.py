"""Audio container and sample integrity checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import wave


_BITRATES_KBPS = {
    (3, 1): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),
    (3, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0),
    (3, 3): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0),
    (2, 1): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
    (2, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
    (2, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
}
_SAMPLE_RATES = {3: (44_100, 48_000, 32_000), 2: (22_050, 24_000, 16_000), 0: (11_025, 12_000, 8_000)}


def _mp3_frame(data: bytes, file_size: int) -> tuple[int, int] | None:
    for offset in range(max(0, len(data) - 3)):
        if data[offset] != 0xFF or data[offset + 1] & 0xE0 != 0xE0:
            continue
        version = (data[offset + 1] >> 3) & 0x03
        layer = (data[offset + 1] >> 1) & 0x03
        bitrate_index = (data[offset + 2] >> 4) & 0x0F
        sample_rate_index = (data[offset + 2] >> 2) & 0x03
        if version == 1 or layer == 0 or sample_rate_index == 3:
            continue
        mpeg_version = 3 if version == 3 else 2 if version == 2 else 0
        bitrate_table_version = 3 if mpeg_version == 3 else 2
        bitrate = _BITRATES_KBPS[(bitrate_table_version, layer)][bitrate_index]
        if not bitrate:
            continue
        sample_rate = _SAMPLE_RATES[mpeg_version][sample_rate_index]
        padding = (data[offset + 2] >> 1) & 1
        if layer == 3:
            frame_size = (12 * bitrate * 1000 // sample_rate + padding) * 4
        else:
            coefficient = 144 if version == 3 or layer == 1 else 72
            frame_size = coefficient * bitrate * 1000 // sample_rate + padding
        if offset + frame_size <= file_size:
            channels = 1 if data[offset + 3] >> 6 == 3 else 2
            return sample_rate, channels
    return None


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    container: str
    size_bytes: int
    sample_rate: int | None
    channels: int | None
    duration_seconds: float | None


def validate_audio(path: Path) -> AudioMetadata:
    if not path.is_file() or path.stat().st_size < 12:
        raise ValueError("Generated audio is missing or incomplete.")
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                frame_rate = audio.getframerate()
                frames = audio.getnframes()
                channels = audio.getnchannels()
                if not frame_rate or not frames or not channels:
                    raise ValueError("Generated WAV audio contains no playable samples.")
                return AudioMetadata(
                    "wav",
                    path.stat().st_size,
                    frame_rate,
                    channels,
                    frames / frame_rate,
                )
        except (wave.Error, EOFError, OSError) as exc:
            raise ValueError("Generated WAV file is corrupt or incomplete.") from exc
    if path.suffix.lower() == ".mp3":
        size = path.stat().st_size
        frame = _mp3_frame(path.read_bytes()[:4096], size)
        if frame is None:
            raise ValueError("Generated MP3 file does not contain a complete MPEG audio frame.")
        return AudioMetadata("mp3", size, frame[0], frame[1], None)
    raise ValueError("Unsupported audio container.")

"""Asynchronous local, Azure, and optional Edge speech synthesis."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiogen_ai.audio_processor import process_audio
from audiogen_ai.audio_validator import AudioMetadata, validate_audio
from audiogen_ai.azure_tts import synthesize_ssml
from audiogen_ai.config import Settings, VOICES
from audiogen_ai.local_tts import synthesize_wav
from audiogen_ai.narration_engine import NarrationProfile, build_ssml, delivery_adjustments
from audiogen_ai.text_processor import prepare_text
from audiogen_ai.validation import (
    sanitize_filename,
    split_text,
    validate_adjustment,
    validate_output_format,
    validate_text,
    validate_voice,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    path: Path
    output_format: str
    chunks: int
    size_bytes: int
    prepared_text: str
    metadata: AudioMetadata


def _speech_factory(text: str, voice: str, rate: str, pitch: str, volume: str) -> Any:
    try:
        import edge_tts
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The optional Edge TTS dependency is missing. Install AUDIOGEN AI "
            "with the [edge] extra only if you intend to use Edge TTS."
        ) from exc

    return edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)


class SpeechEngine:
    def __init__(
        self,
        settings: Settings,
        speech_factory: Callable[[str, str, str, str, str], Any] = _speech_factory,
    ) -> None:
        self.settings = settings
        self.audio_dir = (settings.data_dir / "audio").resolve()
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self._speech_factory = speech_factory
        self._semaphore = asyncio.Semaphore(settings.concurrency)

    @property
    def local_available(self) -> bool:
        return shutil.which(self.settings.espeak_path) is not None

    @property
    def edge_available(self) -> bool:
        return importlib.util.find_spec("edge_tts") is not None

    @property
    def ffmpeg_available(self) -> bool:
        return shutil.which(self.settings.ffmpeg_path) is not None

    async def synthesize(
        self,
        text: str,
        voice: str,
        filename: str = "speech",
        output_format: str = "mp3",
        rate: int = 0,
        pitch: int = 0,
        volume: int = 100,
        progress: ProgressCallback | None = None,
        narration_style: str = "Classroom Teacher",
        sentence_pause_ms: int = 350,
        paragraph_pause_ms: int = 700,
        pronunciations: dict[str, str] | None = None,
        url_policy: str = "read",
        normalize_audio: bool = False,
        sample_rate: int | None = None,
    ) -> SynthesisResult:
        text = validate_text(text, self.settings.max_text_chars)
        voice = validate_voice(voice)
        voice_config = VOICES[voice]
        if voice_config.provider == "azure" and not self.settings.azure_configured:
            raise RuntimeError(
                "Azure is an optional provider and is not configured. Select local eSpeak NG "
                "to synthesize without cloud credentials."
            )
        output_format = validate_output_format(output_format)
        rate = validate_adjustment(rate, "Speed")
        pitch = validate_adjustment(pitch, "Pitch")
        if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
            raise ValueError("Volume must be a whole number between 0 and 100.")
        if sample_rate not in {None, 16_000, 22_050, 24_000, 48_000}:
            raise ValueError("Sample rate must be 16000, 22050, 24000, or 48000 Hz.")
        prepared_text = prepare_text(text, pronunciations, url_policy)
        if not prepared_text:
            raise ValueError("Speech preparation removed all text. Review your URL policy.")
        chunks = split_text(prepared_text, self.settings.chunk_chars)
        safe_name = sanitize_filename(filename)
        output_path = self.audio_dir / f"{uuid.uuid4().hex}_{safe_name}.{output_format}"

        profile = NarrationProfile(
            style=narration_style,
            speed_percent=100 + rate,
            volume_percent=volume,
            pitch_hz=pitch,
            sentence_pause_ms=sentence_pause_ms,
            paragraph_pause_ms=paragraph_pause_ms,
        )
        source_path: Path | None = None
        async with self._semaphore:
            if voice_config.provider == "local":
                handle = tempfile.NamedTemporaryFile(
                    prefix="audiogen-local-", suffix=".wav", dir=self.audio_dir, delete=False
                )
                source_path = Path(handle.name)
                handle.close()
                try:
                    await synthesize_wav(
                        chunks,
                        voice_config.synthesis_id or voice_config.language_code,
                        source_path,
                        executable=self.settings.espeak_path,
                        speed_percent=100 + rate,
                        pitch_hz=pitch,
                        volume_percent=volume,
                        timeout=self.settings.request_timeout,
                        progress=progress,
                    )
                except BaseException:
                    source_path.unlink(missing_ok=True)
                    raise
            else:
                azure_voice = voice_config.synthesis_id or voice
                source_path = await self._synthesize_mp3(
                    chunks,
                    voice,
                    azure_voice,
                    voice_config.provider,
                    profile,
                    rate,
                    pitch,
                    volume,
                    progress,
                )
            try:
                source_sample_rate = 22_050 if voice_config.provider == "local" else 24_000
                needs_processing = (
                    source_path.suffix.lower() != f".{output_format}"
                    or normalize_audio
                    or sample_rate not in {None, source_sample_rate}
                )
                if needs_processing:
                    await process_audio(
                        source_path,
                        output_path,
                        ffmpeg_path=self.settings.ffmpeg_path,
                        normalize=normalize_audio,
                        sample_rate=sample_rate,
                        timeout=self.settings.request_timeout,
                    )
                else:
                    os.replace(source_path, output_path)
            except BaseException:
                output_path.unlink(missing_ok=True)
                raise
            finally:
                source_path.unlink(missing_ok=True)
        try:
            metadata = validate_audio(output_path)
        except ValueError:
            output_path.unlink(missing_ok=True)
            raise
        result = SynthesisResult(
            path=output_path,
            output_format=output_format,
            chunks=len(chunks),
            size_bytes=output_path.stat().st_size,
            prepared_text=prepared_text,
            metadata=metadata,
        )
        logger.info("Generated %s audio in %d chunk(s)", output_format, len(chunks))
        return result

    async def _synthesize_mp3(
        self,
        chunks: list[str],
        voice: str,
        azure_voice: str,
        provider: str,
        profile: NarrationProfile,
        rate: int,
        pitch: int,
        volume: int,
        progress: ProgressCallback | None,
    ) -> Path:
        handle = tempfile.NamedTemporaryFile(
            prefix="audiogen-", suffix=".mp3", dir=self.audio_dir, delete=False
        )
        mp3_path = Path(handle.name)
        try:
            with handle:
                for index, chunk in enumerate(chunks, start=1):
                    audio_data = await self._synthesize_chunk(
                        chunk,
                        voice,
                        azure_voice,
                        provider,
                        profile,
                        rate,
                        pitch,
                        volume,
                        index,
                    )
                    handle.write(audio_data)
                    handle.flush()
                    if progress is not None:
                        progress(index, len(chunks))
            return mp3_path
        except BaseException:
            mp3_path.unlink(missing_ok=True)
            raise

    async def _synthesize_chunk(
        self,
        text: str,
        voice: str,
        azure_voice: str,
        provider: str,
        profile: NarrationProfile,
        rate: int,
        pitch: int,
        volume: int,
        index: int,
    ) -> bytes:
        for attempt in range(self.settings.retries + 1):
            try:
                async with asyncio.timeout(self.settings.request_timeout):
                    if provider == "azure":
                        return await synthesize_ssml(
                            build_ssml(text, azure_voice, profile),
                            key=self.settings.azure_speech_key or "",
                            region=self.settings.azure_speech_region or "",
                            output_format="mp3",
                            timeout=self.settings.request_timeout,
                            retries=0,
                        )
                    voice_config = VOICES[voice]
                    edge_voice = voice_config.synthesis_id or voice
                    style_rate, style_pitch = delivery_adjustments(profile.style)
                    edge_rate = max(-30, min(30, rate + style_rate))
                    edge_pitch = max(-50, min(50, pitch + style_pitch))
                    communicate = self._speech_factory(
                        text,
                        edge_voice,
                        f"{edge_rate:+d}%",
                        f"{edge_pitch:+d}Hz",
                        f"{volume - 100:+d}%",
                    )
                    audio_data = bytearray()
                    async for message in communicate.stream():
                        if message.get("type") == "audio":
                            audio_data.extend(message["data"])
                    if not audio_data:
                        raise RuntimeError("The speech provider returned no audio.")
                    return bytes(audio_data)
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt >= self.settings.retries:
                    logger.exception(
                        "%s speech synthesis failed for chunk %d", provider, index
                    )
                    raise
                delay = min(0.5 * (2**attempt), 4.0)
                logger.warning(
                    "%s speech synthesis chunk %d failed; retrying in %.1f seconds",
                    provider,
                    index,
                    delay,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("Speech synthesis failed unexpectedly.")

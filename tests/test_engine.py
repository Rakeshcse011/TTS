import asyncio
from pathlib import Path
import wave

import pytest

from audiogen_ai.config import Settings
from audiogen_ai.audio_validator import validate_audio
from audiogen_ai.engine import SpeechEngine
from audiogen_ai.library import AudioLibrary

MP3_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 413


class FakeCommunicate:
    failures_remaining = 0
    calls = 0

    def __init__(self, text: str, voice: str, rate: str, pitch: str, volume: str) -> None:
        self.text = text

    async def stream(self):
        type(self).calls += 1
        if type(self).failures_remaining:
            type(self).failures_remaining -= 1
            raise ConnectionError("simulated network failure")
        yield {"type": "WordBoundary", "data": b"ignored"}
        yield {"type": "audio", "data": MP3_FRAME}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, chunk_chars=20, retries=0)


@pytest.mark.asyncio
async def test_synthesis_writes_mp3_and_library_history(settings: Settings) -> None:
    engine = SpeechEngine(settings, FakeCommunicate)
    result = await engine.synthesize("Hello English.", "en-US-AvaNeural", filename="../../story")
    assert result.path.is_file()
    assert result.path.parent == (settings.data_dir / "audio").resolve()
    assert result.path.suffix == ".mp3"
    assert result.size_bytes == len(MP3_FRAME)
    library = AudioLibrary(settings.data_dir)
    record = library.record(result.path.name, "en-US-AvaNeural", "mp3", result.size_bytes)
    assert library.audio_path(record.id) == result.path
    with pytest.raises(ValueError, match="identifier"):
        library.audio_path("..\\private")
    library.delete(record.id)
    assert not result.path.exists()


@pytest.mark.asyncio
async def test_edge_voice_applies_speed_pitch_and_volume(settings: Settings) -> None:
    controls: list[tuple[str, str, str]] = []

    class CaptureCommunicate:
        def __init__(self, text, voice, rate, pitch, volume) -> None:
            controls.append((rate, pitch, volume))

        async def stream(self):
            yield {"type": "audio", "data": MP3_FRAME}

    engine = SpeechEngine(settings, CaptureCommunicate)
    result = await engine.synthesize(
        "Hello.",
        "en-US-AndrewNeural",
        rate=20,
        pitch=10,
        volume=65,
    )
    assert controls == [("+17%", "+10Hz", "-35%")]
    result.path.unlink()


@pytest.mark.asyncio
async def test_edge_narration_preset_adjusts_pace_without_claiming_emotion(
    settings: Settings,
) -> None:
    controls: list[tuple[str, str]] = []

    class CaptureCommunicate:
        def __init__(self, text, voice, rate, pitch, volume) -> None:
            controls.append((rate, pitch))

        async def stream(self):
            yield {"type": "audio", "data": MP3_FRAME}

    engine = SpeechEngine(settings, CaptureCommunicate)
    result = await engine.synthesize(
        "Welcome to our lesson.",
        "edge:en-IN-PrabhatNeural",
        narration_style="Friendly Teacher",
    )
    assert controls == [("+2%", "+1Hz")] * result.chunks
    assert result.path.is_file()
    result.path.unlink()


@pytest.mark.asyncio
async def test_long_text_synthesizes_each_chunk_and_reports_progress(settings: Settings) -> None:
    engine = SpeechEngine(settings, FakeCommunicate)
    progress: list[tuple[int, int]] = []
    result = await engine.synthesize(
        "This is a longer English script for several chunks.",
        "en-US-AvaNeural",
        progress=lambda done, total: progress.append((done, total)),
    )
    assert result.chunks > 1
    assert progress == [(index, result.chunks) for index in range(1, result.chunks + 1)]


@pytest.mark.asyncio
async def test_provider_failure_does_not_leave_audio_file(settings: Settings) -> None:
    class BrokenCommunicate:
        def __init__(self, *args) -> None:
            pass

        async def stream(self):
            raise ConnectionError("offline")
            yield {}

    engine = SpeechEngine(settings, BrokenCommunicate)
    with pytest.raises(ConnectionError):
        await engine.synthesize("नमस्ते", "edge:hi-IN-SwaraNeural")
    assert not list((settings.data_dir / "audio").glob("*.mp3"))


@pytest.mark.asyncio
async def test_network_failure_is_retried(settings: Settings) -> None:
    FakeCommunicate.failures_remaining = 1
    FakeCommunicate.calls = 0
    retry_settings = Settings(data_dir=settings.data_dir, retries=1)
    engine = SpeechEngine(retry_settings, FakeCommunicate)
    result = await engine.synthesize("Hello", "en-US-AvaNeural")
    assert result.path.exists()
    assert FakeCommunicate.calls == 2


@pytest.mark.asyncio
async def test_wav_requires_ffmpeg_when_unavailable(settings: Settings, monkeypatch) -> None:
    import audiogen_ai.engine as engine_module

    import audiogen_ai.audio_processor as processor

    monkeypatch.setattr(processor.shutil, "which", lambda _binary: None)
    engine = SpeechEngine(settings, FakeCommunicate)
    with pytest.raises(RuntimeError, match="requires FFmpeg"):
        await engine.synthesize("Hello", "en-US-AvaNeural", output_format="wav")
    assert not list((settings.data_dir / "audio").glob("*.wav"))


@pytest.mark.asyncio
async def test_wav_output_uses_ffmpeg_without_a_shell(settings: Settings, monkeypatch) -> None:
    import audiogen_ai.engine as engine_module

    import audiogen_ai.audio_processor as processor

    monkeypatch.setattr(processor.shutil, "which", lambda _binary: "ffmpeg.exe")
    commands: list[tuple[str, ...]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        commands.append(args)
        with wave.open(args[-1], "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24_000)
            audio.writeframes(b"\0\0" * 24)
        return FakeProcess()

    monkeypatch.setattr(engine_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    engine = SpeechEngine(settings, FakeCommunicate)
    result = await engine.synthesize("Hello WAV", "en-US-AvaNeural", output_format="wav")
    assert result.path.suffix == ".wav"
    assert validate_audio(result.path).sample_rate == 24_000
    assert commands[0][0] == "ffmpeg.exe"
    assert "-i" in commands[0]
    assert isinstance(commands[0], tuple)


@pytest.mark.asyncio
async def test_local_voice_writes_native_wav_without_ffmpeg(settings: Settings, monkeypatch) -> None:
    import audiogen_ai.local_tts as local_tts

    commands: list[tuple[str, ...]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        commands.append(args)
        destination = Path(args[args.index("-w") + 1])
        with wave.open(str(destination), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(22_050)
            audio.writeframes(b"\0\0" * 220)
        return FakeProcess()

    monkeypatch.setattr(local_tts.shutil, "which", lambda _binary: "espeak-ng.exe")
    monkeypatch.setattr(local_tts.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    engine = SpeechEngine(settings, FakeCommunicate)
    progress: list[tuple[int, int]] = []
    result = await engine.synthesize(
        "Hello local speech.",
        "local:en",
        output_format="wav",
        rate=5,
        pitch=12,
        volume=55,
        progress=lambda done, total: progress.append((done, total)),
    )

    assert result.path.suffix == ".wav"
    assert result.metadata.sample_rate == 22_050
    assert validate_audio(result.path).channels == 1
    assert commands[0][commands[0].index("-s") + 1] == "173"
    assert commands[0][commands[0].index("-p") + 1] == "56"
    assert commands[0][commands[0].index("-a") + 1] == "55"
    assert "-g" not in commands[0]
    assert progress == [(1, 1)]
    result.path.unlink()


@pytest.mark.asyncio
async def test_local_voice_reports_missing_executable(settings: Settings, monkeypatch) -> None:
    import audiogen_ai.local_tts as local_tts

    monkeypatch.setattr(local_tts.shutil, "which", lambda _binary: None)
    engine = SpeechEngine(settings, FakeCommunicate)
    with pytest.raises(RuntimeError, match="eSpeak NG engine is not installed"):
        await engine.synthesize("Hello local speech.", "local:en", output_format="wav")
    assert not list((settings.data_dir / "audio").glob("*.wav"))


def test_engine_respects_concurrent_request_limit(settings: Settings) -> None:
    async def check_limit() -> int:
        class TrackingCommunicate:
            active = 0
            peak = 0

            def __init__(self, *args) -> None:
                pass

            async def stream(self):
                type(self).active += 1
                type(self).peak = max(type(self).peak, type(self).active)
                try:
                    await asyncio.sleep(0.01)
                    yield {"type": "audio", "data": MP3_FRAME}
                finally:
                    type(self).active -= 1

        limited_settings = Settings(data_dir=settings.data_dir, concurrency=1)
        engine = SpeechEngine(limited_settings, TrackingCommunicate)
        await asyncio.gather(
            *(
                engine.synthesize(f"request {number}", "en-US-AvaNeural")
                for number in range(3)
            )
        )
        return TrackingCommunicate.peak

    assert asyncio.run(check_limit()) == 1

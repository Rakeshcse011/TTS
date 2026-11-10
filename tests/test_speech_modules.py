import asyncio
from pathlib import Path
import wave

import httpx
import pytest

from audiogen_ai import azure_tts
from audiogen_ai.audio_processor import process_audio
from audiogen_ai.audio_validator import validate_audio
from audiogen_ai.config import Settings
from audiogen_ai.engine import SpeechEngine
from audiogen_ai.language_detector import detect_language
from audiogen_ai.library import AudioLibrary
from audiogen_ai.narration_engine import NarrationProfile, build_ssml
from audiogen_ai.text_processor import number_to_words, prepare_text
from audiogen_ai.voice_calibration import VoiceProfile


def test_local_provider_is_default_without_azure_configuration(monkeypatch) -> None:
    monkeypatch.delenv("AUDIOGEN_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    settings = Settings.from_env()
    assert settings.default_provider == "local"
    assert not settings.azure_configured
    assert VoiceProfile().provider == "local"
    assert VoiceProfile().accent == "International"
    assert VoiceProfile().output_format == "wav"


def test_windows_espeak_installation_is_discovered_without_path(monkeypatch, tmp_path: Path) -> None:
    import audiogen_ai.config as config

    program_files = tmp_path / "Program Files"
    install_dir = program_files / "eSpeak NG"
    install_dir.mkdir(parents=True)
    executable = install_dir / "espeak-ng.exe"
    executable.write_bytes(b"test")
    monkeypatch.setattr(config.os, "name", "nt")
    monkeypatch.setattr(config.os, "environ", {"ProgramFiles": str(program_files)})
    monkeypatch.setattr(config.shutil, "which", lambda _binary: None)
    assert config.default_espeak_path() == str(executable)


def _wav(path: Path, sample_rate: int = 24_000) -> None:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(b"\0\0" * (sample_rate // 100))


def test_language_detector_handles_hindi_english_and_hinglish() -> None:
    assert detect_language("The lesson starts now").language == "english"
    assert detect_language("आज हम पढ़ेंगे").language == "hindi"
    result = detect_language("आज हम Artificial Intelligence सीखेंगे")
    assert result.language == "mixed"
    assert result.recommendation == "hi-IN-MadhurNeural"
    assert detect_language("aaj hum Artificial Intelligence seekhenge").language == "mixed"


def test_numbers_currency_units_dates_and_times_are_spoken_naturally() -> None:
    prepared = prepare_text(
        "₹5,000. ₹2.5. 5 km. 10/11/2026, November 10, 2026, at 9:05 AM."
    )
    assert "five thousand rupees" in prepared
    assert "two rupees and fifty paise" in prepared
    assert "five kilometers" in prepared
    assert "ten November two thousand twenty six" in prepared
    assert prepared.count("ten November two thousand twenty six") == 2
    assert "nine oh five am" in prepared
    assert number_to_words(123_456) == "one lakh twenty three thousand four hundred fifty six"


def test_math_abbreviations_acronyms_and_water_are_explicit() -> None:
    prepared = prepare_text("A + B = C. Dr. Sharma uses AI. NASA studies H₂O, etc.")
    assert "A plus B equals C" in prepared
    assert "Doctor Sharma" in prepared
    assert "A I" in prepared
    assert "NASA" in prepared
    assert "H two O" in prepared
    assert "et cetera" in prepared
    assert prepare_text("NASA", {"NASA": "N A S A"}) == "N A S A"


def test_custom_pronunciation_and_url_policy_are_editable() -> None:
    assert prepare_text("Kubernetes", {"Kubernetes": "koo-ber-net-eez"}) == "koo-ber-net-eez"
    read = prepare_text("[example](https://example.com)", url_policy="read")
    skipped = prepare_text("[example](https://example.com)", url_policy="omit")
    assert "example.com" in read
    assert skipped == "example"
    with pytest.raises(ValueError, match="URL policy"):
        prepare_text("hello", url_policy="invalid")


def test_ssml_escapes_text_and_applies_style_and_pause_controls() -> None:
    ssml = build_ssml(
        "A & B. Next <lesson>.\n\nNew paragraph.",
        "hi-IN-MadhurNeural",
        NarrationProfile(style="Friendly Teacher", speed_percent=100),
    )
    assert "xml:lang=\"hi-IN\"" in ssml
    assert "A &amp; B." in ssml
    assert "&lt;lesson&gt;" in ssml
    assert 'rate="102%"' in ssml
    assert 'time="200ms"' in ssml
    assert 'time="500ms"' in ssml


def test_calibration_profiles_are_validated_and_persisted(tmp_path: Path) -> None:
    library = AudioLibrary(tmp_path)
    profile = VoiceProfile()
    library.save_voice_profile(profile.name, profile.to_json())
    stored = VoiceProfile.from_json(library.voice_profiles()[profile.name])
    assert stored == profile
    with pytest.raises(ValueError, match="speed"):
        VoiceProfile.from_json(profile.to_json().replace('"speed_percent": 100', '"speed_percent": 200'))


def test_pronunciation_dictionary_stores_categories(tmp_path: Path) -> None:
    library = AudioLibrary(tmp_path)
    library.save_pronunciation("ISRO", "I S R O", "Acronym")
    assert library.pronunciations() == {"ISRO": "I S R O"}
    assert library.pronunciation_entries() == [("ISRO", "I S R O", "Acronym")]
    with pytest.raises(ValueError, match="category"):
        library.save_pronunciation("NASA", "NASA", "Invalid")


def test_audio_integrity_accepts_wav_and_rejects_bad_files(tmp_path: Path) -> None:
    wav_path = tmp_path / "lesson.wav"
    _wav(wav_path)
    metadata = validate_audio(wav_path)
    assert metadata.sample_rate == 24_000
    assert metadata.channels == 1
    assert metadata.duration_seconds == 0.01
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"RIFF-not-a-wave")
    with pytest.raises(ValueError, match="corrupt"):
        validate_audio(broken)


def test_mp3_integrity_rejects_non_audio_bytes(tmp_path: Path) -> None:
    path = tmp_path / "broken.mp3"
    path.write_bytes(b"not an mp3 file")
    with pytest.raises(ValueError, match="MPEG audio frame"):
        validate_audio(path)
    path.write_bytes(b"\xff\xfb\x90\x64" + b"\0" * 12)
    with pytest.raises(ValueError, match="complete MPEG"):
        validate_audio(path)


@pytest.mark.asyncio
async def test_audio_processing_applies_normalization_and_sample_rate(tmp_path: Path, monkeypatch) -> None:
    import audiogen_ai.audio_processor as processor

    source = tmp_path / "source.mp3"
    source.write_bytes(b"fake source")
    destination = tmp_path / "normalized.wav"
    monkeypatch.setattr(processor.shutil, "which", lambda _binary: "ffmpeg.exe")
    commands: list[tuple[str, ...]] = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, **kwargs):
        commands.append(args)
        _wav(Path(args[-1]), 48_000)
        return Process()

    monkeypatch.setattr(processor.asyncio, "create_subprocess_exec", fake_exec)
    await process_audio(source, destination, normalize=True, sample_rate=48_000)
    assert "-af" in commands[0]
    assert "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000" in commands[0]
    assert validate_audio(destination).sample_rate == 48_000


@pytest.mark.asyncio
async def test_audio_merge_normalizes_mixed_inputs_before_concatenating(
    tmp_path: Path, monkeypatch
) -> None:
    import audiogen_ai.audio_processor as processor

    sources = [tmp_path / "first.mp3", tmp_path / "second.wav"]
    for path in sources:
        path.write_bytes(b"audio")
    destination = tmp_path / "merged.mp3"
    monkeypatch.setattr(processor.shutil, "which", lambda _binary: "ffmpeg.exe")
    commands: list[tuple[str, ...]] = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, **kwargs):
        commands.append(args)
        Path(args[-1]).write_bytes(b"merged")
        return Process()

    monkeypatch.setattr(processor.asyncio, "create_subprocess_exec", fake_exec)
    assert await processor.merge_audio(sources, destination) == destination
    assert "aresample=24000" in commands[0][commands[0].index("-filter_complex") + 1]
    assert commands[0][-2:] == ("[out]", str(destination))
    assert destination.read_bytes() == b"merged"


@pytest.mark.asyncio
async def test_azure_speech_uses_authorized_endpoint_and_mp3_header() -> None:
    captured: dict[str, object] = {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, content, headers):
            captured.update(url=url, content=content, headers=headers)
            return httpx.Response(200, content=b"\xff\xfb\x90\x64" + b"\0" * 413)

    audio = await azure_tts.synthesize_ssml(
        "<speak/>",
        key="secret",
        region="eastus",
        output_format="mp3",
        timeout=1,
        client_factory=lambda **_kwargs: Client(),
    )
    assert audio.startswith(b"\xff\xfb\x90\x64")
    assert captured["url"] == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert captured["headers"]["Ocp-Apim-Subscription-Key"] == "secret"
    assert captured["headers"]["X-Microsoft-OutputFormat"].endswith("mp3")


@pytest.mark.asyncio
async def test_azure_retries_transient_errors_and_rejects_authentication(monkeypatch) -> None:
    class Client:
        def __init__(self) -> None:
            self.statuses = [429, 200]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            status = self.statuses.pop(0)
            return httpx.Response(status, content=b"audio" if status == 200 else b"busy")

    async def no_wait(_delay: float) -> None:
        return None

    monkeypatch.setattr(azure_tts.asyncio, "sleep", no_wait)
    audio = await azure_tts.synthesize_ssml(
        "<speak/>",
        key="secret",
        region="eastus",
        output_format="mp3",
        timeout=1,
        client_factory=lambda **_kwargs: Client(),
    )
    assert audio == b"audio"

    class Unauthorized(Client):
        async def post(self, *args, **kwargs):
            return httpx.Response(401)

    with pytest.raises(azure_tts.AzureSpeechError, match="rejected"):
        await azure_tts.synthesize_ssml(
            "<speak/>",
            key="wrong",
            region="eastus",
            output_format="mp3",
            timeout=1,
            retries=0,
            client_factory=lambda **_kwargs: Unauthorized(),
        )


@pytest.mark.asyncio
async def test_azure_network_failure_is_reported_without_disclosing_credentials() -> None:
    class OfflineClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    with pytest.raises(azure_tts.AzureSpeechError, match="connect"):
        await azure_tts.synthesize_ssml(
            "<speak/>",
            key="secret-not-for-logs",
            region="eastus",
            output_format="mp3",
            timeout=1,
            retries=0,
            client_factory=lambda **_kwargs: OfflineClient(),
        )


@pytest.mark.asyncio
async def test_engine_azure_voice_builds_ssml_without_logging_source(
    tmp_path: Path, monkeypatch
) -> None:
    captured: list[str] = []

    async def fake_azure(ssml, **kwargs):
        captured.append(ssml)
        return b"\xff\xfb\x90\x64" + b"\0" * 413

    monkeypatch.setattr("audiogen_ai.engine.synthesize_ssml", fake_azure)
    engine = SpeechEngine(
        Settings(
            data_dir=tmp_path,
            azure_speech_key="test-key",
            azure_speech_region="eastus",
        )
    )
    result = await engine.synthesize(
        "₹5,000. Dr. Sharma teaches AI.",
        "en-IN-PrabhatNeural",
        volume=80,
        narration_style="Classroom Teacher",
    )
    assert result.prepared_text == "five thousand rupees. Doctor Sharma teaches A I."
    assert 'volume="80%"' in captured[0]
    assert "secret" not in captured[0]
    assert result.path.is_file()
    result.path.unlink()


@pytest.mark.asyncio
async def test_azure_is_optional_and_local_provider_is_recommended(tmp_path: Path) -> None:
    engine = SpeechEngine(Settings(data_dir=tmp_path))
    with pytest.raises(RuntimeError, match="Azure is an optional provider"):
        await engine.synthesize("Lesson text.", "en-IN-PrabhatNeural")

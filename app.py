"""Premium AUDIOGEN AI voice studio. Run with: streamlit run app.py."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from collections.abc import Callable
from dataclasses import replace

import streamlit as st

from audiogen_ai.audio_processor import merge_audio
from audiogen_ai.config import Settings, VOICES
from audiogen_ai.documents import extract_document_text
from audiogen_ai.engine import SpeechEngine
from audiogen_ai.language_detector import detect_language
from audiogen_ai.library import AudioLibrary
from audiogen_ai.text_processor import prepare_text
from audiogen_ai.validation import sanitize_filename
from audiogen_ai.voice_calibration import PREVIEW_TEXT, VoiceProfile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="AUDIOGEN AI", page_icon="🔊", layout="wide")
st.markdown(
    """
    <style>
    .stApp { background: radial-gradient(ellipse at 70% -15%, #21344d 0, #0b111b 42%); color: #edf2fb; }
    [data-testid="stSidebar"] { background: #0d1521; border-right: 1px solid #263449; }
    [data-testid="stHeader"] { background: rgba(11, 17, 27, .78); }
    [data-testid="stSidebar"] [data-testid="stRadio"] label { padding: .3rem 0; }
    [data-testid="stMetric"] {
      background: rgba(20, 29, 43, .85); border: 1px solid #2b3b52; padding: 16px; border-radius: 14px;
    }
    .hero { padding: 22px 26px; margin: 8px 0 24px; border: 1px solid #30445e;
      border-radius: 20px; background: linear-gradient(115deg, rgba(20,34,52,.96), rgba(17,25,39,.72)); }
    .hero h1 { letter-spacing: -0.045em; font-size: clamp(2rem, 4vw, 3rem); margin: 8px 0 4px; }
    .hero p { color: #a7b6ca; margin: 0; font-size: 1.02rem; }
    .eyebrow { color: #7dd3c7; font-size: .75rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
    div.stButton > button[kind="primary"] { border: 0; border-radius: 12px; min-height: 3rem;
      background: linear-gradient(100deg, #18a999, #3279c7); font-weight: 700; }
    div.stButton > button { border-radius: 10px; }
    [data-testid="stExpander"] { border-color: #29394e; border-radius: 12px; }
    [data-testid="stFileUploader"] { border-radius: 12px; }
    .stCaption { color: #9aabc1; }
    .creator-card { margin-top: 1.5rem; padding: 14px; border: 1px solid #29394e;
      border-radius: 14px; background: linear-gradient(145deg, rgba(24,36,53,.9), rgba(15,23,35,.9)); }
    .creator-card .creator-label { color: #7dd3c7; font-size: .68rem; font-weight: 700;
      letter-spacing: .12em; text-transform: uppercase; margin: 0 0 8px; }
    .creator-card .creator-name { color: #edf2fb; font-weight: 650; font-size: .93rem; margin: 0 0 3px; }
    .creator-card .creator-degree { color: #a7b6ca; font-size: .8rem; margin: 0 0 9px; }
    .creator-card a { color: #8bc5ff; font-size: .8rem; text-decoration: none; }
    .creator-card a:hover { text-decoration: underline; }
    </style>
    """,
    unsafe_allow_html=True,
)

settings = Settings.from_env()
library = AudioLibrary(settings.data_dir)
engine = SpeechEngine(settings)

_PROFILE_WIDGETS = {
    "profile_name": "Indian Teacher",
    "provider": settings.default_provider,
    "voice": "local:en" if settings.default_provider == "local" else "edge:en-IN-PrabhatNeural",
    "language_preference": "Auto detect",
    "accent": "International" if settings.default_provider == "local" else "Indian",
    "style": "Classroom Teacher",
    "speed": 96 if settings.default_provider == "edge" else 100,
    "volume": 100,
    "pitch": 0,
    "sentence_pause": 350,
    "paragraph_pause": 700,
    "sample_rate": 22_050 if settings.default_provider == "local" else 24_000,
    "normalize_audio": False,
    "url_policy": "read",
    "output_format": "wav" if settings.default_provider == "local" else "mp3",
}
if settings.default_provider == "azure":
    _PROFILE_WIDGETS["provider"] = "azure"
    _PROFILE_WIDGETS["voice"] = "en-IN-PrabhatNeural"
elif settings.default_provider == "edge":
    _PROFILE_WIDGETS["provider"] = "edge"
    _PROFILE_WIDGETS["voice"] = "edge:en-IN-PrabhatNeural"
for key, value in _PROFILE_WIDGETS.items():
    st.session_state.setdefault(key, value)
st.session_state.setdefault("_provider_seen", st.session_state["provider"])

app_password = os.environ.get("AUDIOGEN_APP_PASSWORD")
if app_password and not st.session_state.get("_authenticated", False):
    st.markdown(
        '<div class="hero"><span class="eyebrow">Private voice workspace</span>'
        "<h1>AUDIOGEN AI</h1><p>Sign in to open your voice studio.</p></div>",
        unsafe_allow_html=True,
    )
    with st.form("app-login"):
        entered_password = st.text_input("Access password", type="password")
        login = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if login:
        if hmac.compare_digest(entered_password, app_password):
            st.session_state["_authenticated"] = True
            st.rerun()
        st.error("Incorrect access password.")
    st.stop()


def current_profile() -> VoiceProfile:
    return VoiceProfile(
        name=st.session_state["profile_name"].strip() or "Indian Teacher",
        provider=st.session_state["provider"],
        voice=st.session_state["voice"],
        language=st.session_state["language_preference"],
        accent=st.session_state["accent"],
        style=st.session_state["style"],
        speed_percent=st.session_state["speed"],
        volume_percent=st.session_state["volume"],
        pitch_hz=st.session_state["pitch"],
        sentence_pause_ms=st.session_state["sentence_pause"],
        paragraph_pause_ms=st.session_state["paragraph_pause"],
        sample_rate=st.session_state["sample_rate"],
        normalize_audio=st.session_state["normalize_audio"],
        url_policy=st.session_state["url_policy"],
        output_format=st.session_state["output_format"],
    )


def load_profile(serialized: str) -> None:
    profile = VoiceProfile.from_json(serialized)
    values = {
        "profile_name": profile.name,
        "provider": profile.provider,
        "voice": profile.voice,
        "language_preference": profile.language,
        "accent": profile.accent,
        "style": profile.style,
        "speed": profile.speed_percent,
        "volume": profile.volume_percent,
        "pitch": profile.pitch_hz,
        "sentence_pause": profile.sentence_pause_ms,
        "paragraph_pause": profile.paragraph_pause_ms,
        "sample_rate": profile.sample_rate,
        "normalize_audio": profile.normalize_audio,
        "url_policy": profile.url_policy,
        "output_format": profile.output_format,
    }
    st.session_state.update(values)
    st.session_state["_provider_seen"] = profile.provider


def render_voice_controls(spoken_text: str = "") -> VoiceProfile:
    st.text_input("Voice profile name", key="profile_name", max_chars=64)
    provider = st.selectbox(
        "Speech provider",
        ["local", "azure", "edge"],
        format_func=lambda value: (
            "eSpeak NG · local CPU · compact install"
            if value == "local"
            else "Azure AI Speech · optional integration"
            if value == "azure"
            else "Neural voice · online Edge service"
        ),
        key="provider",
    )
    if st.session_state["_provider_seen"] != provider:
        st.session_state["sample_rate"] = 22_050 if provider == "local" else 24_000
        st.session_state["output_format"] = "wav" if provider == "local" else "mp3"
        st.session_state["_provider_seen"] = provider
    if provider == "local" and not engine.local_available:
        st.warning(
            "Local eSpeak NG is unavailable. Install it or select Neural voice for natural "
            "online speech."
        )
    elif provider == "local":
        st.caption(
            "Offline and private. eSpeak NG is lightweight but synthetic-sounding; select "
            "Neural voice for a more natural result."
        )
    elif provider == "azure" and not settings.azure_configured:
        st.warning(
            "Azure requires your own configured resource. Choose Neural voice for online neural "
            "speech without Azure credentials."
        )
    elif provider == "edge":
        if not engine.edge_available:
            st.warning('Install the optional dependency with `pip install -e ".[edge]"` to enable this voice.')
        else:
            st.info(
                "Natural neural voices run online. Text is sent to the speech service; "
                "internet access is required. Delivery presets adjust pace and pitch, not emotion."
            )

    detected = detect_language(spoken_text) if spoken_text else None
    language_options = ["Auto detect", "Hindi", "Indian English", "English (US)", "English (UK)"]
    st.selectbox("Language", language_options, key="language_preference")
    if detected:
        st.caption(
            f"Detected: **{detected.language.title()}** · "
            f"Suggested single voice: `{detected.recommendation}`. "
            "Mixed-language scripts keep one voice throughout."
        )
        if st.session_state["language_preference"] == "Auto detect":
            detection_key = hashlib.sha256(
                f"{provider}\0{spoken_text}".encode("utf-8")
            ).hexdigest()
            if st.session_state.get("last_detection_key") != detection_key:
                if provider == "local":
                    st.session_state["voice"] = (
                        "local:hi"
                        if detected.hindi_characters > 0
                        or detected.recommendation == "hi-IN-MadhurNeural"
                        else "local:en"
                    )
                else:
                    recommendation = (
                        f"edge:{detected.recommendation}"
                        if provider == "edge"
                        else detected.recommendation
                    )
                    if (
                        recommendation in VOICES
                        and VOICES[recommendation].provider == provider
                    ):
                        st.session_state["voice"] = recommendation
                st.session_state["last_detection_key"] = detection_key
        else:
            st.session_state.pop("last_detection_key", None)
    else:
        st.session_state.pop("last_detection_key", None)

    language_preference = st.session_state["language_preference"]
    language_voices = [
        (voice_id, voice)
        for voice_id, voice in VOICES.items()
        if voice.provider == provider
        and (
            language_preference == "Auto detect"
            or language_preference == "Hindi"
            and voice.language_code in {"hi-IN", "hi"}
            or language_preference == "Indian English"
            and voice.language_code in {"en-IN", "en"}
            or language_preference == "English (US)"
            and voice.language_code == "en-US"
            or language_preference == "English (UK)"
            and voice.language_code == "en-GB"
        )
    ]
    available_accents = sorted({voice.accent for _, voice in language_voices})
    if not available_accents:
        st.error("No voices match this provider and language.")
        return current_profile()
    if st.session_state["accent"] not in available_accents:
        st.session_state["accent"] = available_accents[0]
    st.selectbox("Accent", available_accents, key="accent")
    available_voices = [
        voice_id
        for voice_id, voice in language_voices
        if voice.accent == st.session_state["accent"]
    ]
    if not available_voices:
        st.error("No voices match this provider and language.")
        return current_profile()
    if st.session_state["voice"] not in available_voices:
        st.session_state["voice"] = (
            (
                "local:hi"
                if provider == "local" and language_preference == "Hindi"
                else "local:en"
                if provider == "local"
                else "en-IN-PrabhatNeural"
                if provider == "azure"
                else "edge:hi-IN-MadhurNeural"
                if provider == "edge" and language_preference == "Hindi"
                else "edge:en-IN-PrabhatNeural"
                if provider == "edge"
                else available_voices[0]
            )
        )
        if st.session_state["voice"] not in available_voices:
            st.session_state["voice"] = available_voices[0]
    st.selectbox(
        "Voice",
        available_voices,
        key="voice",
        format_func=lambda value: (
            f"{VOICES[value].name} · {VOICES[value].gender} · "
            f"{VOICES[value].language} · {VOICES[value].accent} accent"
        ),
    )
    st.selectbox(
        "Narration style",
        [
            "Classroom Teacher",
            "Friendly Teacher",
            "Professional Narrator",
            "Confident Presenter",
        ],
        key="style",
        disabled=provider == "local",
    )
    if provider == "local":
        st.caption(
            "eSpeak NG uses unstyled speech. It applies speed, pitch, and volume; custom "
            "sentence/paragraph pauses and narration styles are unavailable locally."
        )
    elif provider == "edge":
        st.caption(
            "Delivery preset changes pace and pitch only; it does not add emotion or alter "
            "the meaning of your text."
        )
    speed, volume = st.columns(2)
    speed.slider("Speaking speed", 70, 130, key="speed", format="%d%%")
    volume.slider("Volume", 0, 100, key="volume", format="%d%%")
    pitch, sample_rate = st.columns(2)
    pitch.slider(
        "Pitch adjustment (eSpeak scale)" if provider == "local" else "Pitch adjustment",
        -50,
        50,
        key="pitch",
        format="%d" if provider == "local" else "%d Hz",
    )
    sample_rate.selectbox(
        "Sample rate",
        [16_000, 22_050, 24_000, 48_000],
        key="sample_rate",
        format_func=lambda value: f"{value // 1000} kHz",
    )
    pauses, paragraph = st.columns(2)
    pauses.slider(
        "Sentence pause",
        0,
        2000,
        key="sentence_pause",
        format="%d ms",
        disabled=provider != "azure",
    )
    paragraph.slider(
        "Paragraph pause",
        0,
        5000,
        key="paragraph_pause",
        format="%d ms",
        disabled=provider != "azure",
    )
    st.selectbox(
        "URL reading",
        ["read", "omit"],
        key="url_policy",
        format_func=lambda value: "Read URL aloud" if value == "read" else "Skip URLs",
    )
    st.checkbox("Normalize final audio (FFmpeg required)", key="normalize_audio")
    st.selectbox("Export format", ["wav", "mp3"], key="output_format")
    profile = current_profile()
    if profile.provider == "local" and not engine.ffmpeg_available:
        needs_ffmpeg = (
            profile.output_format == "mp3"
            or profile.normalize_audio
            or profile.sample_rate != 22_050
        )
        if needs_ffmpeg:
            st.caption(
                "The selected local MP3, normalization, or sample-rate conversion requires "
                "FFmpeg. Native 22.05 kHz WAV works without it."
            )
    return profile


def generate_audio(
    text: str,
    profile: VoiceProfile,
    filename: str,
    progress: Callable[[int, int], None] | None = None,
):
    return asyncio.run(
        engine.synthesize(
            text=text,
            voice=profile.voice,
            filename=sanitize_filename(filename),
            output_format=profile.output_format,
            rate=profile.speed_percent - 100,
            pitch=profile.pitch_hz,
            volume=profile.volume_percent,
            progress=progress,
            narration_style=profile.style,
            sentence_pause_ms=profile.sentence_pause_ms,
            paragraph_pause_ms=profile.paragraph_pause_ms,
            pronunciations=library.pronunciations(),
            url_policy=profile.url_policy,
            normalize_audio=profile.normalize_audio,
            sample_rate=profile.sample_rate,
        )
    )


def synthesis_issue(profile: VoiceProfile) -> str | None:
    if profile.provider == "local" and not engine.local_available:
        return "Install eSpeak NG or select the online neural voice."
    if profile.provider == "edge" and not engine.edge_available:
        return 'Install the optional Edge dependency with `pip install -e ".[edge]"`.'
    if profile.provider == "azure" and not settings.azure_configured:
        return "Azure is not configured. Select the online neural voice or local eSpeak NG."
    source_rate = 22_050 if profile.provider == "local" else 24_000
    needs_ffmpeg = (
        profile.output_format == "mp3" and profile.provider == "local"
        or profile.output_format == "wav" and profile.provider != "local"
        or profile.normalize_audio
        or profile.sample_rate != source_rate
    )
    if needs_ffmpeg and not engine.ffmpeg_available:
        return "This output option requires FFmpeg. Use native-rate WAV locally or MP3 online."
    return None


def synthesis_ready(profile: VoiceProfile) -> bool:
    return synthesis_issue(profile) is None


def render_audio_result(result, label: str) -> None:
    record = library.record(
        result.path.name, st.session_state["voice"], result.output_format, result.size_bytes
    )
    audio = result.path.read_bytes()
    st.success(
        f"{label} ready · {result.chunks} speech part(s) · "
        f"{result.metadata.size_bytes:,} bytes"
    )
    st.audio(audio, format=f"audio/{result.output_format}")
    st.download_button(
        "⬇ Download audio",
        data=audio,
        file_name=result.path.name,
        mime=f"audio/{result.output_format}",
        key=f"download-{record.id}",
    )
    with st.expander("Audio metadata"):
        st.json(
            {
                "format": result.metadata.container,
                "size_bytes": result.metadata.size_bytes,
                "sample_rate": result.metadata.sample_rate,
                "channels": result.metadata.channels,
                "duration_seconds": result.metadata.duration_seconds,
            }
        )


profile_rows = library.voice_profiles()
st.sidebar.markdown("# 🔊 AUDIOGEN AI")
st.sidebar.caption("Indian teacher voice studio · Hindi · English · Hinglish")
st.sidebar.markdown(
    '<div class="creator-card">'
    '<p class="creator-label">Designed &amp; developed by</p>'
    '<p class="creator-name">R. K. Prajapati</p>'
    '<p class="creator-degree">MTech (IS)</p>'
    '<a href="mailto:rakeshcse011@gmail.com">rakeshcse011@gmail.com</a>'
    "</div>",
    unsafe_allow_html=True,
)
if profile_rows:
    selected_profile = st.sidebar.selectbox("Saved voice profiles", ["Current settings", *profile_rows])
    if selected_profile != "Current settings" and st.sidebar.button("Load profile"):
        load_profile(profile_rows[selected_profile])
        st.rerun()
page = st.sidebar.radio(
    "Workspace",
    ["Voice Studio", "Voice Calibration", "Pronunciation Dictionary", "Library", "Settings"],
    label_visibility="collapsed",
)

if page == "Voice Studio":
    st.markdown(
        '<div class="hero"><span class="eyebrow">AUDIOGEN AI · VOICE STUDIO</span>'
        "<h1>Give every lesson a voice.</h1>"
        "<p>Prepare, preview, and narrate Hindi, Indian English, and mixed-language lessons.</p></div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.12, 0.88], gap="large")
    with left:
        mode = st.radio("Create", ["Single lesson", "Batch"], horizontal=True)
        uploaded = st.file_uploader("Import a text document", type=["txt", "pdf"], max_upload_size=10)
        if uploaded is not None:
            try:
                data = uploaded.getvalue()
                upload_hash = hashlib.sha256(data).hexdigest()
                if st.session_state.get("loaded_upload") != upload_hash:
                    st.session_state["draft"] = extract_document_text(
                        uploaded.name, data, settings.max_upload_bytes
                    )
                    st.session_state["loaded_upload"] = upload_hash
                    st.success(f"Loaded text from {uploaded.name}")
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(str(exc))
        else:
            st.session_state.pop("loaded_upload", None)
        text = st.text_area(
            "Lesson script",
            key="draft",
            height=270,
            max_chars=settings.max_text_chars,
            placeholder="Paste an educational lesson or article…",
        )
        st.caption(f"{len(text):,} / {settings.max_text_chars:,} characters")
        filename = st.text_input("Project name", value="My lesson", max_chars=100)
    with right:
        profile = render_voice_controls(text)
    prepared = prepare_text(text, library.pronunciations(), profile.url_policy) if text.strip() else ""
    original, spoken = st.columns(2)
    with original:
        with st.expander("Original text", expanded=False):
            st.text(text or "Your source text appears here.")
    with spoken:
        with st.expander("Prepared spoken text", expanded=True):
            st.text(prepared or "Speech-ready text appears here.")
    synthesis_problem = synthesis_issue(profile)
    if synthesis_problem:
        st.warning(synthesis_problem)
    elif not text.strip():
        st.caption("Add lesson text or import a document to enable generation.")
    generate = st.button(
        "Generate lesson audio",
        type="primary",
        use_container_width=True,
        disabled=bool(synthesis_problem) or not text.strip(),
    )
    if generate:
        scripts = (
            [line.strip() for line in text.splitlines() if line.strip()]
            if mode == "Batch"
            else [text]
        )
        if not scripts:
            st.error("Enter some lesson text before generating audio.")
            st.stop()
        if mode == "Batch" and len(scripts) > 20:
            st.error("A batch can contain at most 20 scripts.")
            st.stop()
        progress = st.progress(0, text="Preparing narration…")
        try:
            for index, script in enumerate(scripts, start=1):
                def update_progress(done: int, total: int, lesson_index: int = index) -> None:
                    fraction = (lesson_index - 1 + done / total) / len(scripts)
                    progress.progress(
                        fraction,
                        text=f"Generating lesson {lesson_index} · part {done} of {total}",
                    )

                result = generate_audio(
                    script,
                    profile,
                    f"{filename}-{index}" if mode == "Batch" else filename,
                    progress=update_progress,
                )
                render_audio_result(result, f"Lesson {index}")
                progress.progress(index / len(scripts), text=f"Completed {index} of {len(scripts)}")
        except Exception as exc:
            logging.exception("Speech generation failed")
            st.error(f"Speech generation failed. Check your connection/provider settings and retry: {exc}")

elif page == "Voice Calibration":
    st.title("Voice calibration studio")
    st.caption(
        "Preview your settings before saving. Provider-specific speech controls are applied "
        "only where the selected engine supports them."
    )
    profile = render_voice_controls()
    signature = profile.to_json()
    preview_col, comparison_col = st.columns(2)
    with preview_col:
        preview_format = "wav" if profile.provider == "local" else "mp3"
        preview_rate = 22_050 if profile.provider == "local" else 24_000
        preview_profile = replace(
            profile,
            output_format=preview_format,
            normalize_audio=False,
            sample_rate=preview_rate,
        )
        if st.button(
            "▶ Generate ~10-second preview",
            type="primary",
            disabled=not synthesis_ready(preview_profile),
        ):
            try:
                result = generate_audio(PREVIEW_TEXT, preview_profile, "voice-preview")
                st.session_state["voice_preview"] = result.path.read_bytes()
                st.session_state["voice_preview_format"] = result.output_format
                result.path.unlink(missing_ok=True)
                st.session_state["preview_signature"] = signature
            except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
                st.error(f"Preview failed: {exc}")
        if st.session_state.get("voice_preview"):
            st.audio(
                st.session_state["voice_preview"],
                format=f"audio/{st.session_state['voice_preview_format']}",
            )
            st.caption("Preview generated with the current controls. Provider timing varies by voice.")
    with comparison_col:
        comparison_voices = [
            voice_id for voice_id, item in VOICES.items() if item.provider == profile.provider
        ]
        compare_voice = st.selectbox(
            "Compare another voice",
            comparison_voices,
            format_func=lambda value: (
                f"{VOICES[value].name} · {VOICES[value].gender} · {VOICES[value].language}"
            ),
        )
        comparison_profile = replace(
            profile,
            voice=compare_voice,
            output_format=preview_format,
            normalize_audio=False,
            sample_rate=preview_rate,
        )
        if st.button(
            "Generate comparison preview",
            disabled=not synthesis_ready(comparison_profile),
        ):
            try:
                comparison = generate_audio(
                    PREVIEW_TEXT, comparison_profile, "voice-comparison"
                )
                st.session_state["comparison_preview"] = comparison.path.read_bytes()
                st.session_state["comparison_preview_format"] = comparison.output_format
                comparison.path.unlink(missing_ok=True)
            except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
                st.error(f"Comparison preview failed: {exc}")
        if st.session_state.get("comparison_preview"):
            st.audio(
                st.session_state["comparison_preview"],
                format=f"audio/{st.session_state['comparison_preview_format']}",
            )
    st.divider()
    preview_is_current = st.session_state.get("preview_signature") == signature
    if not preview_is_current:
        st.info("Generate a preview with the current settings before finalizing this voice profile.")
    if st.button("✓ Finalize and save preferred voice profile", disabled=not preview_is_current):
        library.save_voice_profile(profile.name, profile.to_json())
        st.success(f"Saved **{profile.name}** to persistent application storage.")

elif page == "Pronunciation Dictionary":
    st.title("Pronunciation dictionary")
    st.caption("Only your explicit entries override how a word or phrase is spoken.")
    with st.form("pronunciation-form", clear_on_submit=True):
        word = st.text_input("Word or phrase")
        pronunciation = st.text_input("Speak it as")
        category = st.selectbox(
            "Category",
            ["General", "Hindi", "English", "Acronym", "Technical", "Proper name"],
        )
        save_word = st.form_submit_button("Save pronunciation")
    if save_word:
        try:
            library.save_pronunciation(word, pronunciation, category)
            st.success(f"Saved pronunciation for **{word}**.")
        except ValueError as exc:
            st.error(str(exc))
    entries = library.pronunciation_entries()
    if entries:
        selected_term = st.selectbox(
            "Preview a difficult word",
            [entry[0] for entry in entries],
        )
        entry = next(item for item in entries if item[0] == selected_term)
        st.caption(f"Pronunciation: **{entry[1]}** · {entry[2]}")
        if st.button("▶ Preview this word", disabled=not synthesis_ready(current_profile())):
            profile = current_profile()
            try:
                result = generate_audio(
                    selected_term, profile, f"word-{selected_term}"
                )
                st.audio(
                    result.path.read_bytes(), format=f"audio/{result.output_format}"
                )
                result.path.unlink(missing_ok=True)
            except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
                st.error(f"Word preview failed: {exc}")
        if st.button("Delete pronunciation"):
            library.delete_pronunciation(selected_term)
            st.rerun()
        st.dataframe(
            [
                {"Word or phrase": term, "Spoken as": alias, "Category": kind}
                for term, alias, kind in entries
            ],
            use_container_width=True,
            hide_index=True,
        )

elif page == "Library":
    st.title("Generation history")
    records = library.recent(50)
    if not records:
        st.info("Your generated audio will appear here.")
    else:
        selected_ids = st.multiselect(
            "Recent projects to merge (select at least two)",
            [record.id for record in records],
            format_func=lambda record_id: next(
                record.filename for record in records if record.id == record_id
            ),
        )
        if not engine.ffmpeg_available:
            st.caption("Install FFmpeg to merge audio files.")
        if st.button(
            "Merge selected audio",
            disabled=len(selected_ids) < 2 or not engine.ffmpeg_available,
        ):
            try:
                sources = [library.audio_path(record_id) for record_id in selected_ids]
                merged = library.audio_dir / f"merged-{hashlib.sha256('|'.join(selected_ids).encode()).hexdigest()[:16]}.mp3"
                asyncio.run(merge_audio(sources, merged, ffmpeg_path=settings.ffmpeg_path))
                library.record(merged.name, "merged", "mp3", merged.stat().st_size)
                st.success("Merged audio saved to your history.")
                st.rerun()
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(f"Audio merge failed: {exc}")
        for record in records:
            with st.container(border=True):
                st.markdown(f"**{record.filename}**")
                voice_name = VOICES[record.voice].name if record.voice in VOICES else record.voice
                st.caption(
                    f"{voice_name} · {record.output_format.upper()} · "
                    f"{record.size_bytes:,} bytes · {record.created_at[:16].replace('T', ' ')} UTC"
                )
                try:
                    path = library.audio_path(record.id)
                    audio = path.read_bytes()
                    st.audio(audio, format=f"audio/{record.output_format}")
                    download, deletion = st.columns(2)
                    download.download_button(
                        "Download",
                        audio,
                        file_name=record.filename,
                        mime=f"audio/{record.output_format}",
                        key=f"library-download-{record.id}",
                    )
                    if deletion.button("Delete", key=f"library-delete-{record.id}"):
                        library.delete(record.id)
                        st.rerun()
                except FileNotFoundError:
                    st.warning("Audio file is missing.")

else:
    st.title("Settings & deployment")
    st.caption("Choose the local private engine or the more natural online neural voice.")
    st.write(f"Storage: `{settings.data_dir}`")
    st.write(f"Local eSpeak NG available: **{'Yes' if engine.local_available else 'No'}**")
    st.write(f"Online neural voice package available: **{'Yes' if engine.edge_available else 'No'}**")
    st.write(f"FFmpeg available: **{'Yes' if engine.ffmpeg_available else 'No'}**")
    st.write(f"Password protection enabled: **{'Yes' if app_password else 'No'}**")
    st.caption(
        "Online neural synthesis sends the selected text to the provider. Check its current "
        "privacy and voice-use terms before using sensitive or commercial content."
    )
    st.write("The API stays disabled until `AUDIOGEN_API_KEY` is configured.")
    st.code(
        '$env:AUDIOGEN_API_KEY = "use-a-long-random-secret"\n'
        "python -m uvicorn audiogen_ai.api:app --app-dir src --host 127.0.0.1 --port 8000",
        language="powershell",
    )
    st.warning(
        "Check the selected engine and individual voice/data license before commercial distribution. "
        "eSpeak NG is GPL-3-or-later; online voice services may have separate usage terms."
    )

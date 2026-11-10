# AUDIOGEN AI

A local-first voice studio for educational narration in Hindi, English, and
mixed-language (Hinglish) scripts. The default engine is eSpeak NG, a compact,
CPU-only local synthesizer; it requires neither an API key nor a model download.
For more natural neural speech, select the optional online Edge voice and use an
Indian voice such as Prabhat; text is sent to that online provider. The Render
Blueprint selects this neural voice by default. Azure Speech remains optional.
eSpeak NG is formant-based rather than neural and does not sound like a natural
Indian male teacher; it remains available for offline fallback.

## What is implemented

- Dark Streamlit studio with source/spoken-text preview, TXT/PDF import, single
  lesson and line-based batch jobs, progress, audio playback, and download.
- Voice calibration with an approximately 10-second sample, comparison sample,
  four speaking profiles, and an explicit **Finalize and save** action. Profiles
  persist in the local SQLite database.
- Conservative text normalization for Indian currency grouping, dates, times,
  measurements, basic equations, `Dr.`/`Mr.`/`Prof.`, `etc.`, `H₂O`, and `AI`.
  Unrecognized acronyms and proper nouns are left alone. User pronunciation rules
  take precedence and are editable by word, Hindi, English, acronym, technical,
  or proper-name category.
- Whole-script Hindi/English/Hinglish detection and a suggested single voice;
  voices are not switched mid-sentence.
- Authenticated optional FastAPI interface, local generation history, FFmpeg
  normalization/resampling/merge support, and WAV/MP3 integrity checks.
- Direct 22.05 kHz local WAV export; FFmpeg is needed for local MP3, normalization,
  resampling, and merging.
- Delivery presets apply supported pace/pitch adjustments. They do not claim to
  synthesize emotion or change the source meaning.

Text normalization is rule-based, not an LLM: it does not invent explanations.
Inspect the prepared spoken-text preview before synthesis. No pronunciation
guessing is made for unknown proper names or acronyms. URL reading can be set to
read or omit.

## Requirements and installation (Windows PowerShell)

- Windows 10/11 and Python 3.12, 3.13, or 3.14.
- The official eSpeak NG Windows package on `PATH` for local speech.
- FFmpeg on `PATH` for local MP3 output, normalization, non-default sample-rate
  conversion, or merging. WAV at the engine's native sample rate works without it.
- Internet access and provider credentials only if you explicitly select an
  online provider.

From `C:\Users\pc\TTS`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m streamlit run app.py
```

For the optional natural neural voice, install its online provider adapter:

```powershell
python -m pip install -e ".[edge]"
```

In the UI, select **Neural voice · online Edge service**. The service needs
internet access and receives the text being synthesized; it does not require an
Azure key. eSpeak NG remains local and offline.

Install eSpeak NG from the [official Windows
releases](https://github.com/espeak-ng/espeak-ng/releases) and ensure
`espeak-ng.exe` is on `PATH` (or set `AUDIOGEN_ESPEAK_PATH`). The application uses
eSpeak NG's installed executable and data; it does not download large model
weights.

In the provided `uv` environment:

```powershell
uv sync --extra dev
uv run streamlit run app.py
```

Use **WAV** for a direct local export without FFmpeg. MP3 export and audio
normalization/resampling require FFmpeg.

## Sample workflow

1. Install eSpeak NG, then open **Voice Studio**.
2. Paste a lesson such as `आज हम Artificial Intelligence सीखेंगे। AI हमारे काम आता है।`
   The selected single voice is used for the entire script.
3. Review the detected language, original text, and **Prepared spoken text**. Add
   an explicit pronunciation in **Pronunciation Dictionary** if required.
4. For a natural neural voice, choose **Neural voice · online Edge service** and
   an Indian English or Hindi voice. For offline use, choose eSpeak NG; it
   supports speed, relative pitch, and volume but sounds more synthetic.
5. In **Voice Calibration**, generate and listen to a preview. Adjust and regenerate
   as needed; optionally compare a second voice.
6. Only after a preview of the current settings, click **Finalize and save
   preferred voice profile**. Profile settings are persisted locally.
7. Generate the complete lesson. Play or download the audio and inspect its
   validated container metadata in the studio or history.

The preview text is sized for approximately ten seconds. Actual duration varies
by voice and provider; this is not a hard real-time cutoff or a promise of exactly
10.000 seconds.

## Optional online providers

Azure Speech and Edge TTS are not needed to install or run the application. They
are opt-in integrations; selecting Azure requires an existing Azure Speech
subscription/resource and credentials, while Edge TTS transmits selected text to
its online service. No Azure resource or payment account is requested or required
for the local workflow. Install the optional dependency with
`python -m pip install -e ".[azure]"` or `".[edge]"` only when intentionally
enabling that provider. Edge TTS accesses an unofficial online integration; it
may be rate-limited or changed and is not a service-level or commercial-use
guarantee. Confirm provider, voice, privacy, and commercial-use terms before
production workloads.

## Render deployment

The repository includes a Render Blueprint in [`render.yaml`](./render.yaml).
Connect the repository to Render and deploy the Blueprint. It configures the
online neural voice, generated UI password, health check, and persistent audio
storage. The Blueprint uses a paid Starter service because Render persistent
disks are not available on the free tier. See [`DEPLOYMENT.md`](./DEPLOYMENT.md)
for the sign-in and provider limitations.

## REST API

The API is disabled until `AUDIOGEN_API_KEY` is set:

```powershell
$env:AUDIOGEN_API_KEY = "use-a-long-random-secret"
python -m uvicorn audiogen_ai.api:app --app-dir src --host 127.0.0.1 --port 8000
```

All endpoints except `/health` require `X-API-Key`. The in-process limiter permits
30 calls/minute/client; JSON request bodies are capped at 512 KiB. For example:

```powershell
$headers = @{ "X-API-Key" = $env:AUDIOGEN_API_KEY }
Invoke-RestMethod http://127.0.0.1:8000/v1/voices -Headers $headers

$body = @{
  text = "आज हम Artificial Intelligence सीखेंगे।"
  voice = "local:hi"
  output_format = "wav"
  rate = 0
  pitch = 0
  volume = 100
  narration_style = "Classroom Teacher"
} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/v1/synthesize `
  -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

`POST /v1/synthesize` returns a generated ID and authenticated download URL.
`GET /v1/audio/{id}` downloads it. API input uses a signed speed adjustment
(`rate` -50 to 50), pitch (-50 to 50 Hz), and volume (0 to 100 percent). The
built-in limiter is not shared across worker processes. Do not expose this service
publicly without HTTPS, deployment-grade identity/access control, a shared rate
limiter, request monitoring, and retention controls. See [DEPLOYMENT.md](./DEPLOYMENT.md).

## Data, privacy, and configuration

- `AUDIOGEN_DATA_DIR`: per-user data directory override.
- `AUDIOGEN_TTS_PROVIDER`: default provider (`local`, `azure`, or `edge`; default `local`).
- `AUDIOGEN_ESPEAK_PATH`: eSpeak NG executable override.
- `AUDIOGEN_APP_PASSWORD`: optional password gate for the Streamlit interface;
  unset for local development. Set a strong secret for a hosted deployment.
- `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`: optional Azure integration only.
- `AUDIOGEN_API_KEY`: enables the optional API.
- `AUDIOGEN_FFMPEG_PATH`: FFmpeg executable override.
- Default Windows storage: `%LOCALAPPDATA%\AudioGenAI`.
- SQLite stores generation metadata, pronunciation entries, and saved voice
  profiles, but not the original script. Audio files are stored locally until
  deleted from **Library**.
- Synthesis transmits the selected text and voice/settings to the chosen online
  provider. Confirm provider licensing, privacy, consent, and intended commercial
  use. This app does not clone voices; do not imitate real people without consent.

## Tests and performance

Run the deterministic, offline suite:

```powershell
uv run pytest
```

The suite mocks live provider responses and FFmpeg subprocesses. Passing tests do
not verify local-engine availability/quality, live provider access, real FFmpeg
encoding, or playback on a physical device. See
[PERFORMANCE.md](./PERFORMANCE.md) for the actual test run and outstanding
hardware/integration benchmarks.

Current bounds: text up to 100,000 characters, 2,800-character chunks, two
concurrent provider jobs, 45-second per-request timeout, and two exponential
retries for online providers. Original user text is not logged. eSpeak NG runs
locally on CPU without neural model inference; voice quality depends on its
installed language assets.

## Windows executable

On Windows, after installing the application and PyInstaller:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onedir --name AUDIOGEN_AI `
  --collect-all streamlit `
  --add-data "app.py;." launcher.py
```

This is an unverified packaging recipe, not a signed installer. Bundle and test
all installed application modules and static assets on a clean Windows machine.
eSpeak NG (including its data files) and FFmpeg remain external prerequisites
unless separately packaged in compliance with their licenses.

## Engine and voice licensing

eSpeak NG is licensed under GPL-3.0-or-later. Commercial use is not categorically
prohibited, but redistribution and modified-work obligations apply. Verify the
exact installer, included language data, notices, and obligations before
commercial redistribution; licensing for individual data files in a third-party
installer has not been independently established here. The local engine uses no
separately learned voice weights; verify the licensing of any alternative voice
data distribution.

IndicF5 was evaluated but not downloaded. Its gated
[model card](https://huggingface.co/ai4bharat/IndicF5) identifies MIT-licensed
model code/weights and reports roughly 350.7 million FP32 parameters (about
1.4 GB of weights), requiring approved access, reference audio, and transcript.
The card requires permission for voice cloning; commercial rights for each
reference recording/voice and practical CPU performance on 8 GB RAM were not
verified. It is therefore not selected as the default. A model license alone
does not grant rights to the voice or reference audio.

## Source layout

```text
app.py                              Streamlit voice studio
launcher.py                         Optional PyInstaller launcher
src/audiogen_ai/config.py           Settings and provider voice catalog
src/audiogen_ai/local_tts.py        Local eSpeak NG CPU synthesis
src/audiogen_ai/azure_tts.py        Authenticated Azure Speech REST client
src/audiogen_ai/engine.py           Async synthesis, chunking, retry, audio output
src/audiogen_ai/text_processor.py   Conservative speech-text preparation
src/audiogen_ai/language_detector.py Hindi/English/Hinglish suggestion
src/audiogen_ai/pronunciation_engine.py Explicit dictionary substitutions
src/audiogen_ai/narration_engine.py SSML/prosody and pause generation
src/audiogen_ai/voice_calibration.py Validated persistent profile model
src/audiogen_ai/audio_processor.py  FFmpeg normalize/resample/merge
src/audiogen_ai/audio_validator.py  WAV/MP3 output integrity and metadata
src/audiogen_ai/library.py          Private audio, profiles, dictionary, history
src/audiogen_ai/api.py              Optional authenticated FastAPI service
tests/                              Offline unit, API and provider tests
```

## Known limitations

Voice timing is provider-dependent; previews are approximate-duration samples.
Language detection is heuristic and never performs word-level multi-voice
switching. Text rules intentionally avoid general-purpose acronym guessing;
add project-specific pronunciations explicitly. Prosody and pause controls are
applied only by providers that support them.
eSpeak NG's formant-based voices are not neural Indian male teacher voices and
do not implement the named narration styles or custom pauses. Scanned-PDF OCR,
speaker diarization, subtitle output, asynchronous API job cancellation, and
production identity/observability are not implemented.

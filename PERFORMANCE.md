# AUDIOGEN AI performance and QA report

## Latest executed test run (neural voice and Render update)

| Check | Result |
|---|---|
| Environment | Windows, Python 3.12.10 |
| Command | `uv lock --check --offline`; `uv run --offline python -m compileall -q src tests app.py launcher.py`; `uv run --offline pytest` |
| Python compilation | Passed |
| Automated tests | 49 passed, 0 failed |
| Test-suite elapsed time | 5.47 seconds |
| eSpeak NG live synthesis | Passed; produced a valid 22.05 kHz WAV |
| Edge live synthesis | Passed; Indian English Prabhat produced a valid 24 kHz MP3 |
| Edge Hindi/Hinglish synthesis | Passed; Hindi male voice produced valid 24 kHz MP3s |
| Render Blueprint | YAML parsed and required service settings verified |
| Password gate | Passed Streamlit AppTest login smoke test |
| Azure live synthesis | Not run |
| FFmpeg encode/decode | Not run; FFmpeg is not installed |
| 8 GB peak-memory/latency benchmark | Not run |

Coverage includes text preparation for Hindi/English/Hinglish examples, numbers,
Indian currency, dates, times, equations, abbreviations, acronyms, water formula,
URL modes, user pronunciations, SSML escaping/styles/pauses, Azure
authentication/retry/network error handling, local provider defaults, local
synthesis command options and missing-engine behavior, Edge delivery preset
controls, voice profile persistence,
WAV/MP3 integrity, FFmpeg normalization/resampling invocation, concurrency,
history, document import, and API authentication/body-size limits.

Tests use deterministic provider and FFmpeg fakes. The live Edge check confirms
the current service returned a valid MP3, not subjective voice quality or future
service availability. The Render service has not been deployed. Tests do not
prove Azure account configuration, real FFmpeg codecs, physical-device playback,
or production performance. Pytest emitted one upstream Starlette deprecation
warning about its `httpx`-based `TestClient`.

## Implemented resource controls

- Up to two concurrent synthesis jobs; text capped at 100,000 characters and
  chunked to at most 2,800 characters.
- Azure/Edge requests have a 45-second timeout and up to two exponential-backoff
  retries. Local eSpeak NG synthesis is asynchronous, chunked, and timed out.
  Configuration failures do not log input text or credentials.
- Provider audio is buffered one chunk at a time and appended to a temporary file.
- API JSON bodies are capped at 512 KiB; the in-process rate limiter bounds client
  state and allows 30 requests per minute per address.
- FFmpeg runs as an argument list (never through a shell) with timeout and
  generated-file integrity checks.

## Production performance verification still needed

Run repeated Hindi, Indian English, and mixed-language synthesis with eSpeak NG
and any intentionally enabled online provider on the target hardware. Record
latency, real output duration/size, retry rates, 8 GB peak resident memory, WAV conversion
and normalization time, multi-chunk continuity, concurrency, and physical-device
playback. Do not use the test-suite runtime as a speech speed/latency benchmark.

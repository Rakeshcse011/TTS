# AUDIOGEN AI deployment notes

## Deploy to Render

1. Push this repository to a Git provider and create a Render Blueprint from it.
   Render will read [`render.yaml`](./render.yaml).
2. The Blueprint provisions a Starter web service, a 1 GB persistent disk, and a
   generated `AUDIOGEN_APP_PASSWORD`. Review the plan and disk cost in Render
   before confirming; persistent disks are not available on the free web-service
   tier.
3. After the first deploy, open the service's **Environment** page and copy the
   generated `AUDIOGEN_APP_PASSWORD` from the secret value. Open the service URL
   and sign in. The value is not printed in application logs.
4. The Render configuration selects the online neural Edge voice so lessons
   sound more natural than the local eSpeak NG fallback. Synthesis needs outbound
   internet; text is sent to the speech provider. Edge TTS is an unofficial
   integration, may be rate-limited or changed by its operator, and is not a
   service-level or commercial-use guarantee. For a commercial production
   workload, use a provider contract that explicitly permits your usage.
5. Uploaded/generated audio and saved profiles use `/var/data`. The deployment
   health check is `/_stcore/health`. Keep the generated access password private
   and rotate it in Render if it is exposed.

The password gate protects the Streamlit interface when
`AUDIOGEN_APP_PASSWORD` is set. Render's generated value enables it by default;
if the variable is omitted in another hosting environment, the UI has no login.
The optional FastAPI service is not started by this Blueprint.

## Local production-like Windows setup

1. Install Python 3.12+ and the official eSpeak NG Windows distribution. Install
   FFmpeg from a trusted distribution if MP3 export, audio processing, or merging
   is needed.
2. Create and protect a dedicated Windows user account and local application
   data directory. Do not store credentials in source control or UI configuration.
3. Install from the project root:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -e ".[dev]"
   python -m pytest
   ```

4. Ensure `espeak-ng.exe` and its data files are installed and discoverable on
   `PATH` (or configure `AUDIOGEN_ESPEAK_PATH`). Configure `AUDIOGEN_DATA_DIR` to
   a protected persistent directory, then run `python -m streamlit run app.py`.
5. Local speech works without a network connection or API credentials. If an
   optional cloud provider is explicitly enabled, confirm its endpoint, pricing,
   quota, retention, privacy, and commercial voice-use terms.
6. Back up or apply retention to local SQLite and audio separately. Voice profiles
   and pronunciations are stored in the same SQLite database.

## API deployment

The API is disabled until `AUDIOGEN_API_KEY` is set. The example Uvicorn command
binds to loopback. Before a remote deployment:

- Put an HTTPS reverse proxy/load balancer in front of Uvicorn.
- Replace the single static key with deployment identity and per-user authorization.
- Use a shared/distributed rate limiter, with identity-aware quotas and request
  size/time limits. The in-memory limiter is per-process only.
- Restrict network egress, storage permissions, and admin access. If an optional
  cloud provider is enabled, protect and rotate its credentials.
- Define audio retention/deletion, backup, incident response, and user data
  policies. Apply audio download authorization to every record.
- Monitor only aggregate latency/provider statuses/resource usage; keep text,
  SSML, audio, and secrets out of logs.
- Run provider and FFmpeg integration tests and a 8 GB RAM/concurrency benchmark
  on the actual deployment environment.

This codebase does not yet include a distributed job queue, per-user identity,
distributed rate limiting, deployment telemetry, or an audited retention service.
It should not be exposed directly to the public internet as-is.

## Windows executable

The PyInstaller command in [README.md](./README.md) is a starting point only. Build
on the Windows target architecture; test the complete bundle in a clean VM; verify
Streamlit static assets and package data; keep eSpeak NG and FFmpeg configuration
external unless their licenses and data files have been reviewed for bundling;
then sign and distribute using the organization's trusted installer process.
Neither signing nor clean-machine bundle validation has been performed. eSpeak NG
is GPL-3.0-or-later; review its terms before redistributing it with a commercial
product.

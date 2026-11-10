"""Azure Cognitive Services Speech REST provider."""

from __future__ import annotations

import asyncio
import re

class AzureSpeechError(RuntimeError):
    """Azure Speech returned a structured synthesis failure."""


_OUTPUT_FORMATS = {
    "mp3": "audio-24khz-48kbitrate-mono-mp3",
    "wav": "riff-24khz-16bit-mono-pcm",
}


async def synthesize_ssml(
    ssml: str,
    *,
    key: str,
    region: str,
    output_format: str,
    timeout: float,
    retries: int = 2,
    client_factory=None,
) -> bytes:
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise AzureSpeechError(
            "The optional Azure integration dependency is missing. Install AUDIOGEN AI "
            "with the [azure] extra only if you intend to use Azure."
        ) from exc

    if output_format not in _OUTPUT_FORMATS:
        raise ValueError("Azure output format must be MP3 or WAV.")
    if not key or not region:
        raise AzureSpeechError(
            "The optional Azure provider is not configured. Select the local provider "
            "to synthesize without cloud credentials."
        )
    if not re.fullmatch(r"[a-z0-9-]{2,30}", region, flags=re.IGNORECASE):
        raise AzureSpeechError("Azure Speech region is not a valid region identifier.")
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": _OUTPUT_FORMATS[output_format],
        "User-Agent": "AUDIOGEN-AI",
    }
    if client_factory is None:
        client_factory = httpx.AsyncClient
    async with client_factory(timeout=timeout) as client:
        for attempt in range(retries + 1):
            try:
                response = await client.post(url, content=ssml.encode("utf-8"), headers=headers)
                if response.status_code == 200:
                    if not response.content:
                        raise AzureSpeechError("Azure Speech returned an empty audio response.")
                    return response.content
                if response.status_code not in {408, 429, 500, 502, 503, 504}:
                    raise AzureSpeechError(
                        f"Azure Speech rejected the request (HTTP {response.status_code}). "
                        "Check the region, voice, subscription key, and service quota."
                    )
                if attempt >= retries:
                    raise AzureSpeechError(
                        f"Azure Speech is temporarily unavailable (HTTP {response.status_code})."
                    )
            except httpx.TimeoutException as exc:
                if attempt >= retries:
                    raise AzureSpeechError("Azure Speech request timed out.") from exc
            except httpx.NetworkError as exc:
                if attempt >= retries:
                    raise AzureSpeechError("Could not connect to Azure Speech.") from exc
            await asyncio.sleep(min(0.5 * (2**attempt), 4.0))
    raise AzureSpeechError("Azure Speech synthesis failed.")

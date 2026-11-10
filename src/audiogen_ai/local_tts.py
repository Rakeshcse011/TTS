"""Low-memory CPU-only synthesis through the installed eSpeak NG executable."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path

ProgressCallback = Callable[[int, int], None]


async def synthesize_wav(
    chunks: list[str],
    voice: str,
    destination: Path,
    *,
    executable: str = "espeak-ng",
    speed_percent: int = 100,
    pitch_hz: int = 0,
    volume_percent: int = 100,
    timeout: float = 45.0,
    progress: ProgressCallback | None = None,
) -> Path:
    binary = shutil.which(executable)
    if binary is None:
        raise RuntimeError(
            "The local eSpeak NG engine is not installed or not on PATH. "
            "Install the official Windows eSpeak NG package, then restart AUDIOGEN AI."
        )
    if voice not in {"en", "hi"}:
        raise ValueError("The local engine currently supports English and Hindi voices.")
    if not chunks:
        raise ValueError("No text chunks were provided for local synthesis.")

    sample_rate: int | None = None
    try:
        with wave.open(str(destination), "wb") as output:
            for index, chunk in enumerate(chunks, start=1):
                handle = tempfile.NamedTemporaryFile(
                    prefix="audiogen-local-", suffix=".wav", dir=destination.parent, delete=False
                )
                temporary_path = Path(handle.name)
                handle.close()
                try:
                    speed = round(165 * speed_percent / 100)
                    pitch = max(0, min(99, round(50 + pitch_hz / 2)))
                    amplitude = volume_percent
                    process = await asyncio.create_subprocess_exec(
                        binary,
                        "-v",
                        voice,
                        "-s",
                        str(speed),
                        "-p",
                        str(pitch),
                        "-a",
                        str(amplitude),
                        "-w",
                        str(temporary_path),
                        chunk,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        _, stderr = await asyncio.wait_for(
                            process.communicate(), timeout=timeout
                        )
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                        raise RuntimeError("Local eSpeak NG synthesis timed out.") from None
                    except asyncio.CancelledError:
                        process.kill()
                        await process.wait()
                        raise
                    if process.returncode:
                        message = stderr.decode("utf-8", errors="replace").strip()
                        raise RuntimeError(f"Local eSpeak NG synthesis failed: {message}")
                    with wave.open(str(temporary_path), "rb") as audio:
                        if audio.getnframes() == 0:
                            raise RuntimeError("Local eSpeak NG returned empty audio.")
                        current_rate = audio.getframerate()
                        params = audio.getparams()
                        if sample_rate is None:
                            sample_rate = current_rate
                            output.setparams(params)
                        elif current_rate != sample_rate or params[:3] != output.getparams()[:3]:
                            raise RuntimeError("Local eSpeak NG returned inconsistent WAV settings.")
                        output.writeframes(audio.readframes(audio.getnframes()))
                finally:
                    temporary_path.unlink(missing_ok=True)
                if progress is not None:
                    progress(index, len(chunks))
        if sample_rate is None or destination.stat().st_size <= 44:
            raise RuntimeError("Local eSpeak NG produced an incomplete WAV file.")
        return destination
    except BaseException:
        destination.unlink(missing_ok=True)
        raise

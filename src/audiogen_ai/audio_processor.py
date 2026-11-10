"""Safe FFmpeg normalization, resampling, and audio merging."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil


async def process_audio(
    source: Path,
    destination: Path,
    *,
    ffmpeg_path: str = "ffmpeg",
    normalize: bool = False,
    sample_rate: int | None = None,
    timeout: float = 60.0,
) -> Path:
    ffmpeg = shutil.which(ffmpeg_path)
    if ffmpeg is None:
        raise RuntimeError("Audio processing requires FFmpeg installed on PATH.")
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    filters: list[str] = []
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if sample_rate is not None:
        if sample_rate not in {16_000, 22_050, 24_000, 48_000}:
            raise ValueError("Sample rate must be 16000, 22050, 24000, or 48000 Hz.")
        filters.append(f"aresample={sample_rate}")
    if filters:
        command.extend(["-af", ",".join(filters)])
    if destination.suffix.lower() == ".mp3":
        command.extend(["-codec:a", "libmp3lame", "-q:a", "2"])
    command.append(str(destination))
    await _run(command, timeout)
    return destination


async def merge_audio(
    sources: list[Path], destination: Path, *, ffmpeg_path: str = "ffmpeg", timeout: float = 180.0
) -> Path:
    if len(sources) < 2:
        raise ValueError("Choose at least two audio files to merge.")
    if len(sources) > 100 or any(not path.is_file() for path in sources):
        raise ValueError("Merge supports up to 100 existing audio files.")
    ffmpeg = shutil.which(ffmpeg_path)
    if ffmpeg is None:
        raise RuntimeError("Audio merging requires FFmpeg installed on PATH.")
    normalized_inputs = "".join(
        f"[{index}:a:0]aresample=24000,aformat=sample_fmts=fltp:"
        f"channel_layouts=mono[a{index}];"
        for index in range(len(sources))
    )
    concat_filter = (
        normalized_inputs
        + "".join(f"[a{index}]" for index in range(len(sources)))
        + f"concat=n={len(sources)}:v=0:a=1[out]"
    )
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for source in sources:
        command.extend(["-i", str(source)])
    command.extend(["-filter_complex", concat_filter, "-map", "[out]", str(destination)])
    try:
        await _run(command, timeout)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


async def _run(command: list[str], timeout: float) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, error = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("FFmpeg audio processing timed out.") from None
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        message = error.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg audio processing failed: {message}")

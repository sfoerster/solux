from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import Config
from . import paths
from .process import run_command


class AudioProcessingError(Exception):
    """Raised when ffmpeg audio normalization fails."""


def normalize_audio_to_wav(
    config: Config,
    input_audio: Path,
    source_id: str,
    no_cache: bool = False,
    progress: Callable[[str], None] | None = None,
    verbose: bool = False,
) -> Path:
    """
    Use ffmpeg to convert any input audio file to a 16kHz mono PCM WAV.
    """
    output_wav = paths.normalized_wav_path(config.paths.cache_dir, source_id)
    if output_wav.exists() and not no_cache:
        if progress:
            progress(f"Using cached normalized WAV: {output_wav}")
        return output_wav

    cmd = [
        config.ffmpeg.binary,
        "-y",
        "-i",
        str(input_audio),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(output_wav),
    ]
    try:
        if progress:
            progress(f"Normalizing audio with ffmpeg: {input_audio} -> {output_wav}")
        returncode, command_output = run_command(
            cmd,
            verbose=verbose,
            progress=progress,
            label="ffmpeg",
        )
    except FileNotFoundError as exc:
        raise AudioProcessingError(
            f"ffmpeg binary not found: {config.ffmpeg.binary}. Set [ffmpeg].binary to a valid executable path."
        ) from exc
    if returncode != 0:
        message = command_output.strip() or "unknown ffmpeg failure"
        raise AudioProcessingError(f"ffmpeg failed to normalize audio: {message}")
    if progress:
        progress(f"Normalized WAV ready: {output_wav}")
    return output_wav

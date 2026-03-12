from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .config import Config
from . import paths
from .process import run_command


class TranscriptionError(Exception):
    """Raised when whisper-cli transcription fails."""


def transcribe_audio(
    config: Config,
    wav_path: Path,
    source_id: str,
    no_cache: bool = False,
    progress: Callable[[str], None] | None = None,
    verbose: bool = False,
) -> Path:
    """
    Call whisper-cli to generate a transcript .txt file.
    Returns the transcript path.
    """
    transcript = paths.transcript_path(config.paths.cache_dir, source_id)
    if transcript.exists() and not no_cache:
        if progress:
            progress(f"Using cached transcript: {transcript}")
        return transcript

    cli_path = config.whisper.cli_path
    model_path = config.whisper.model_path
    if not cli_path or not cli_path.exists():
        raise TranscriptionError("whisper-cli not configured or not found. Set [whisper].cli_path in config.toml.")
    if not model_path or not model_path.exists():
        raise TranscriptionError("whisper model not configured or not found. Set [whisper].model_path in config.toml.")

    output_base = transcript.with_suffix("")
    cmd = [
        str(cli_path),
        "-m",
        str(model_path),
        "-f",
        str(wav_path),
        "-otxt",
        "-of",
        str(output_base),
        "-t",
        str(config.whisper.threads),
    ]

    if progress:
        progress(f"Transcribing WAV with whisper-cli: {wav_path}")
    returncode, command_output = run_command(
        cmd,
        verbose=verbose,
        progress=progress,
        label="whisper-cli",
    )
    if returncode != 0:
        message = command_output.strip() or "unknown whisper-cli failure"
        raise TranscriptionError(f"whisper-cli failed: {message}")

    if transcript.exists():
        if progress:
            progress(f"Transcript written: {transcript}")
        return transcript

    fallback = Path(f"{wav_path}.txt")
    if fallback.exists():
        shutil.move(str(fallback), str(transcript))
        if progress:
            progress(f"Transcript moved into cache: {transcript}")
        return transcript

    raise TranscriptionError(f"whisper-cli completed but transcript file was not found at {transcript}")

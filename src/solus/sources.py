from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

from .config import Config
from . import paths
from .process import run_command


class SourceResolutionError(Exception):
    """Raised when source input cannot be resolved to audio."""


AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".ogg", ".wav", ".flac", ".opus", ".webm")


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_direct_audio_url(value: str) -> bool:
    path = urlparse(value).path.lower()
    return any(path.endswith(ext) for ext in AUDIO_EXTENSIONS)


def _download_url_to_path(url: str, destination: Path) -> None:
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    with destination.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=1024 * 64):
            if chunk:
                fh.write(chunk)


def _download_url_to_path_with_progress(
    url: str,
    destination: Path,
    progress: Callable[[str], None] | None = None,
) -> None:
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    total = int(response.headers.get("content-length", "0") or "0")
    downloaded = 0
    next_update = 0.1

    with destination.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=1024 * 64):
            if not chunk:
                continue
            fh.write(chunk)
            downloaded += len(chunk)
            if progress and total > 0:
                frac = downloaded / total
                if frac >= next_update:
                    progress(
                        f"Downloading direct audio... {int(frac * 100)}% "
                        f"({downloaded // (1024 * 1024)} MiB / {total // (1024 * 1024)} MiB)"
                    )
                    next_update += 0.1


def _find_downloaded_audio(source_dir: Path) -> Path | None:
    candidates = sorted(
        p
        for p in source_dir.glob("audio.*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS and p.suffix.lower() != ".wav"
    )
    return candidates[0] if candidates else None


def _looks_like_pyenv_not_found(message: str, tool_name: str) -> bool:
    normalized = message.lower()
    return "pyenv:" in normalized and f"{tool_name}: command not found" in normalized


def resolve_source_to_audio(
    config: Config,
    source: str,
    source_id: str | None = None,
    no_cache: bool = False,
    progress: Callable[[str], None] | None = None,
    verbose: bool = False,
) -> Path:
    """
    Given a source string (URL or file path), return a local audio file path.
    Uses cache directories for downloads.
    """
    source_id = source_id or paths.compute_source_id(source)
    source_cache_dir = paths.source_dir(config.paths.cache_dir, source_id)
    if progress:
        progress(f"Source cache directory: {source_cache_dir}")

    local_path = Path(source).expanduser()
    if local_path.exists() and local_path.is_file():
        if progress:
            progress(f"Using local input file: {local_path.resolve()}")
        return local_path.resolve()

    if not _is_url(source):
        raise SourceResolutionError(f"Source is neither an existing file nor a valid URL: {source}")

    if _is_direct_audio_url(source):
        ext = Path(urlparse(source).path).suffix.lower() or ".audio"
        target = source_cache_dir / f"audio{ext}"
        if target.exists() and not no_cache:
            if progress:
                progress(f"Using cached downloaded audio: {target}")
            return target
        try:
            if progress:
                progress(f"Downloading direct audio URL to: {target}")
            if progress:
                _download_url_to_path_with_progress(source, target, progress)
            else:
                _download_url_to_path(source, target)
        except requests.RequestException as exc:
            raise SourceResolutionError(f"Failed to download audio URL: {exc}") from exc
        if progress:
            progress(f"Downloaded direct audio: {target}")
        return target

    if not no_cache:
        cached_audio = _find_downloaded_audio(source_cache_dir)
        if cached_audio:
            if progress:
                progress(f"Using cached yt-dlp audio: {cached_audio}")
            return cached_audio

    cmd = [
        config.yt_dlp.binary,
        "--no-playlist",
        "--write-info-json",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--output",
        str(source_cache_dir / "audio.%(ext)s"),
        source,
    ]
    try:
        if progress:
            progress("Resolving source via yt-dlp (this may take a while for long videos)")
        returncode, command_output = run_command(
            cmd,
            verbose=verbose,
            progress=progress,
            label="yt-dlp",
        )
    except FileNotFoundError as exc:
        raise SourceResolutionError(
            f"yt-dlp binary not found: {config.yt_dlp.binary}. Set [yt_dlp].binary to a valid executable path."
        ) from exc

    if returncode != 0:
        message = command_output.strip() or "unknown yt-dlp failure"
        if _looks_like_pyenv_not_found(message, "yt-dlp"):
            raise SourceResolutionError(
                "yt-dlp failed from the configured binary due to pyenv shim resolution. "
                "Set [yt_dlp].binary to a direct executable path (for example "
                "~/.pyenv/versions/<env>/bin/yt-dlp) or activate the matching pyenv version."
            )
        raise SourceResolutionError(f"yt-dlp failed: {message}")

    audio_file = _find_downloaded_audio(source_cache_dir)
    if audio_file is None:
        raise SourceResolutionError("yt-dlp completed but no audio file was produced")
    if progress:
        progress(f"yt-dlp produced audio file: {audio_file}")
    return audio_file

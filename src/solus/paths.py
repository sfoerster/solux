from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def compute_source_id(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        payload = source
    else:
        file_path = Path(source).expanduser()
        try:
            resolved = file_path.resolve()
        except OSError:
            resolved = file_path.absolute()
        mtime_ns = file_path.stat().st_mtime_ns if file_path.exists() else 0
        payload = f"{resolved}:{mtime_ns}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def source_dir(cache_dir: Path, source_id: str) -> Path:
    return ensure_dir(cache_dir / "sources" / source_id)


def normalized_wav_path(cache_dir: Path, source_id: str) -> Path:
    return source_dir(cache_dir, source_id) / "audio.wav"


def transcript_path(cache_dir: Path, source_id: str) -> Path:
    return source_dir(cache_dir, source_id) / "transcript.txt"


def summary_path(cache_dir: Path, source_id: str, mode: str, output_format: str) -> Path:
    ext_map = {"markdown": "md", "text": "txt", "json": "json"}
    ext = ext_map.get(output_format, "txt")
    return source_dir(cache_dir, source_id) / f"summary-{mode}.{ext}"


def metadata_path(cache_dir: Path, source_id: str) -> Path:
    return source_dir(cache_dir, source_id) / "metadata.json"


def outputs_dir(cache_dir: Path) -> Path:
    return ensure_dir(cache_dir / "outputs")


def exported_output_path(
    cache_dir: Path,
    source_id: str,
    display_slug: str,
    mode: str,
    output_format: str,
) -> Path:
    ext_map = {"markdown": "md", "text": "txt", "json": "json"}
    ext = ext_map.get(output_format, "txt")
    return outputs_dir(cache_dir) / f"{display_slug}-{source_id}-{mode}.{ext}"

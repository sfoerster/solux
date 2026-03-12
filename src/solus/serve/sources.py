from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class FileEntry:
    name: str
    path: Path
    size_bytes: int
    mtime: float


@dataclass(frozen=True)
class SourceEntry:
    source_id: str
    path: Path
    title: str
    source_input: str | None
    updated_at: float
    files: list[FileEntry]


_TITLE_LOOKUP_CACHE: dict[str, str | None] = {}


def _is_youtube_host(host: str) -> bool:
    return host in {"youtube.com", "youtu.be"} or host.endswith((".youtube.com", ".youtu.be"))


def _read_metadata(source_dir: Path) -> dict[str, Any]:
    meta_path = source_dir / "metadata.json"
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items()}


def _first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    if not values:
        return ""
    return values[0]


def _write_metadata(source_dir: Path, payload: dict[str, Any]) -> None:
    meta_path = source_dir / "metadata.json"
    try:
        meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        return


def _read_infojson_title(source_dir: Path) -> str | None:
    for info_path in sorted(source_dir.glob("*.info.json")):
        try:
            payload = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


def _looks_generic_title(title: str) -> bool:
    lowered = title.strip().lower()
    if lowered in {"watch", "youtube", "youtu.be"}:
        return True
    return lowered.startswith("youtube ")


def _fetch_remote_title_with_ytdlp(source_input: str, yt_dlp_binary: str | None) -> str | None:
    if not yt_dlp_binary:
        return None
    cached = _TITLE_LOOKUP_CACHE.get(source_input)
    if source_input in _TITLE_LOOKUP_CACHE:
        return cached
    parsed = urlparse(source_input)
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"} or not _is_youtube_host(host):
        _TITLE_LOOKUP_CACHE[source_input] = None
        return None

    cmd = [
        yt_dlp_binary,
        "--no-playlist",
        "--skip-download",
        "--print",
        "%(title)s",
        source_input,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=20)
    except (OSError, subprocess.SubprocessError):
        _TITLE_LOOKUP_CACHE[source_input] = None
        return None
    if proc.returncode != 0:
        _TITLE_LOOKUP_CACHE[source_input] = None
        return None
    title = (proc.stdout or "").strip()
    if not title:
        _TITLE_LOOKUP_CACHE[source_input] = None
        return None
    _TITLE_LOOKUP_CACHE[source_input] = title
    return title


def _fallback_title_from_source_input(source_input: str | None, source_id: str) -> str:
    if not source_input:
        return source_id
    parsed = urlparse(source_input)
    if parsed.scheme not in {"http", "https"}:
        local_name = Path(source_input).name
        return local_name or source_input

    host = parsed.netloc.lower()
    query = parse_qs(parsed.query)
    if host == "youtube.com" or host.endswith(".youtube.com"):
        video_id = _first_query_value(query, "v")
        if video_id:
            return f"YouTube {video_id}"
    if host == "youtu.be" or host.endswith(".youtu.be"):
        video_id = Path(parsed.path).name
        if video_id:
            return f"YouTube {video_id}"

    candidate = Path(parsed.path).name
    if candidate and candidate.lower() != "watch":
        return candidate
    cleaned_host = parsed.netloc.removeprefix("www.")
    return f"{cleaned_host}{parsed.path or ''}"


def _source_label(source_input: str | None) -> str:
    if not source_input:
        return ""
    parsed = urlparse(source_input)
    if parsed.scheme in {"http", "https"}:
        host = parsed.netloc.removeprefix("www.")
        query = parse_qs(parsed.query)
        video_id = _first_query_value(query, "v")
        if video_id:
            return f"{host} · v={video_id}"
        path = parsed.path or "/"
        label = f"{host}{path}"
    else:
        label = source_input
    if len(label) > 68:
        return label[:65] + "..."
    return label


def _result_files(source_dir: Path) -> list[FileEntry]:
    entries: list[FileEntry] = []
    for item in source_dir.iterdir():
        if not item.is_file():
            continue
        if item.name == "transcript.txt" or item.name.startswith("summary-") or item.name == "context.json":
            try:
                stat = item.stat()
            except OSError:
                continue
            entries.append(
                FileEntry(
                    name=item.name,
                    path=item,
                    size_bytes=stat.st_size,
                    mtime=stat.st_mtime,
                )
            )

    def _order_key(entry: FileEntry) -> tuple[int, str]:
        if entry.name.startswith("summary-full."):
            return (0, entry.name)
        if entry.name.startswith("summary-tldr."):
            return (1, entry.name)
        if entry.name.startswith("summary-outline."):
            return (2, entry.name)
        if entry.name.startswith("summary-notes."):
            return (3, entry.name)
        if entry.name.startswith("summary-transcript."):
            return (4, entry.name)
        if entry.name == "context.json":
            return (5, entry.name)
        if entry.name == "transcript.txt":
            return (6, entry.name)
        return (7, entry.name)

    return sorted(entries, key=_order_key)


def discover_sources(cache_dir: Path, yt_dlp_binary: str | None = None) -> list[SourceEntry]:
    sources_dir = cache_dir / "sources"
    if not sources_dir.exists():
        return []

    items: list[SourceEntry] = []
    for source_dir in sources_dir.iterdir():
        if not source_dir.is_dir():
            continue
        files = _result_files(source_dir)
        if not files:
            continue
        meta = _read_metadata(source_dir)
        source_input = str(meta.get("source") or "") or None
        raw_title = str(meta.get("display_name") or "").strip()
        title = raw_title
        if not title or _looks_generic_title(title):
            local_title = _read_infojson_title(source_dir)
            if local_title:
                title = local_title
            elif source_input:
                fetched_title = _fetch_remote_title_with_ytdlp(source_input, yt_dlp_binary)
                if fetched_title:
                    title = fetched_title
            if not title or _looks_generic_title(title):
                title = _fallback_title_from_source_input(source_input, source_dir.name)

            if title and title != raw_title:
                updated = dict(meta)
                updated["display_name"] = title
                _write_metadata(source_dir, updated)
        try:
            updated_at = source_dir.stat().st_mtime
        except OSError:
            updated_at = 0.0
        items.append(
            SourceEntry(
                source_id=source_dir.name,
                path=source_dir,
                title=title,
                source_input=str(source_input) if source_input else None,
                updated_at=updated_at,
                files=files,
            )
        )
    return sorted(items, key=lambda item: item.updated_at, reverse=True)


def safe_select_source(entries: list[SourceEntry], source_id: str | None) -> SourceEntry | None:
    if not entries:
        return None
    if source_id:
        for entry in entries:
            if entry.source_id == source_id:
                return entry
    return entries[0]


def safe_select_file(entry: SourceEntry, file_name: str | None) -> FileEntry | None:
    if not entry.files:
        return None
    if file_name:
        for f in entry.files:
            if f.name == file_name:
                return f
    return entry.files[0]

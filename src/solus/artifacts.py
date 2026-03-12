from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import paths


def format_transcript_output(transcript: str, output_format: str) -> str:
    if output_format == "json":
        return json.dumps({"transcript": transcript}, indent=2, ensure_ascii=False)
    return transcript


def _read_ytdlp_title(cache_dir: Path, source_id: str) -> str | None:
    source_cache_dir = paths.source_dir(cache_dir, source_id)
    info_files = sorted(source_cache_dir.glob("*.info.json"))
    for info_file in info_files:
        try:
            payload = json.loads(info_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


def display_name_for_source(
    source: str,
    *,
    input_audio: Path | None = None,
    cache_dir: Path | None = None,
    source_id: str | None = None,
) -> str:
    local = Path(source).expanduser()
    if local.exists():
        return local.name

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if cache_dir and source_id:
            ytdlp_title = _read_ytdlp_title(cache_dir, source_id)
            if ytdlp_title:
                return ytdlp_title
        if input_audio is not None and input_audio.exists() and not input_audio.name.startswith("audio."):
            return input_audio.name
        host = parsed.netloc.lower()
        query = parse_qs(parsed.query)
        if "youtube.com" in host:
            values = query.get("v", [])
            video_id = values[0] if values else ""
            if video_id:
                return f"YouTube {video_id}"
        if "youtu.be" in host:
            video_id = Path(parsed.path).name
            if video_id:
                return f"YouTube {video_id}"
        candidate = Path(unquote(parsed.path)).name
        if candidate and candidate.lower() != "watch":
            return candidate
        return parsed.netloc or source

    return source


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"\s+", "-", lowered)
    lowered = re.sub(r"[^a-z0-9._-]", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered[:80] or "source"


def write_source_metadata(
    cache_dir: Path,
    source_id: str,
    source_input: str,
    input_audio: Path,
    display_name: str,
    workflow_name: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    meta_path = paths.metadata_path(cache_dir, source_id)

    existing: dict[str, str] = {}
    if meta_path.exists():
        try:
            existing_raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(existing_raw, dict):
                existing = {k: str(v) for k, v in existing_raw.items() if isinstance(k, str)}
        except (OSError, json.JSONDecodeError):
            existing = {}

    payload = {
        "source_id": source_id,
        "source": source_input,
        "display_name": display_name,
        "input_audio": str(input_audio),
        "updated_at": now,
        "created_at": existing.get("created_at", now),
    }
    if workflow_name:
        payload["workflow_name"] = workflow_name
    meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

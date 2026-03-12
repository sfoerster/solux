from __future__ import annotations

import json
import subprocess

from solus.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    output_key = str(step.config.get("output_key", "video_urls"))
    limit = int(step.config.get("limit", 50))

    playlist_url = str(ctx.source)
    yt_dlp_bin = str(ctx.config.yt_dlp.binary)

    try:
        proc = subprocess.run(
            [yt_dlp_bin, "--flat-playlist", "--print-json", playlist_url],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"input.youtube_playlist: yt-dlp failed: {exc}") from exc

    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        snippet = message[:200] if message else "unknown error"
        raise RuntimeError(f"input.youtube_playlist: yt-dlp returned {proc.returncode}: {snippet}")

    video_urls: list[str] = []
    playlist_title = ""

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not playlist_title:
            playlist_title = str(entry.get("playlist_title") or entry.get("playlist") or "")

        url = entry.get("url") or entry.get("webpage_url") or ""
        if url:
            video_urls.append(str(url))

        if limit > 0 and len(video_urls) >= limit:
            break

    ctx.data[output_key] = video_urls
    ctx.data["playlist_title"] = playlist_title
    ctx.data["display_name"] = playlist_title or playlist_url
    ctx.logger.info("youtube_playlist: found %d videos in %r", len(video_urls), playlist_title)
    return ctx


MODULE = ModuleSpec(
    name="youtube_playlist",
    version="0.1.0",
    category="input",
    description="Fetch video URLs from a YouTube playlist using yt-dlp.",
    handler=handle,
    aliases=("input.yt_playlist",),
    dependencies=(
        Dependency(
            name="yt-dlp",
            kind="binary",
            check_cmd=("yt-dlp", "--version"),
            hint="pip install yt-dlp",
        ),
    ),
    config_schema=(
        ConfigField(name="output_key", description="Context key for video URL list", default="video_urls"),
        ConfigField(name="limit", description="Max number of videos to fetch", type="int", default=50),
    ),
    reads=(),
    writes=(
        ContextKey("video_urls", "List of video URLs (configurable via output_key)"),
        ContextKey("playlist_title", "Title of the playlist"),
        ContextKey("display_name", "Playlist title or URL"),
    ),
    network=True,
)

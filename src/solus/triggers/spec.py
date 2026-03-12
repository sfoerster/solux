from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Trigger:
    name: str
    type: str  # "folder_watch" | "rss_poll"
    workflow: str
    params: dict  # passed to enqueue_jobs as params
    config: dict  # type-specific config (path/pattern/interval or url/interval)
    enabled: bool = True

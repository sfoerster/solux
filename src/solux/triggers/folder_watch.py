"""FolderWatchTrigger — watches a directory for new files."""

from __future__ import annotations

import fnmatch
import logging
import threading
from pathlib import Path

from ..queueing import enqueue_jobs
from .spec import Trigger
from ._state import _state_db, _is_seen, _mark_seen

logger = logging.getLogger(__name__)


class FolderWatchTrigger:
    def __init__(
        self,
        trigger: Trigger,
        cache_dir: Path,
        state_db_path: Path,
        stop_event: threading.Event,
    ) -> None:
        self.trigger = trigger
        self.cache_dir = cache_dir
        self.state_db_path = state_db_path
        self.stop_event = stop_event

    def run(self) -> None:
        cfg = self.trigger.config
        watch_path = Path(str(cfg.get("path", ""))).expanduser()
        pattern = str(cfg.get("pattern", "*"))
        interval = float(cfg.get("interval", 30))
        trigger_name = self.trigger.name

        real_watch = watch_path.resolve()
        conn = _state_db(self.state_db_path)
        logger.info(
            "trigger[%s]: watching %s (pattern=%r, interval=%.1fs)",
            trigger_name,
            watch_path,
            pattern,
            interval,
        )
        try:
            while not self.stop_event.is_set():
                if watch_path.is_dir():
                    for item in sorted(
                        watch_path.iterdir(),
                        key=lambda p: p.stat().st_mtime if p.is_file() else 0,
                    ):
                        if not item.is_file():
                            continue
                        if not fnmatch.fnmatch(item.name, pattern):
                            continue
                        real_item = item.resolve()
                        if not real_item.is_relative_to(real_watch):
                            logger.warning(
                                "trigger[%s]: skipping %s: resolves outside watch dir",
                                trigger_name,
                                item,
                            )
                            continue
                        key = str(real_item)
                        if not _is_seen(conn, trigger_name, key):
                            # Mark seen before enqueueing so a crash between the two
                            # steps never produces duplicate jobs (prefer at-most-once).
                            _mark_seen(conn, trigger_name, key)
                            logger.info("trigger[%s]: new file detected: %s", trigger_name, item)
                            try:
                                params = {
                                    **dict(self.trigger.params),
                                    "_trigger_name": trigger_name,
                                    "_trigger_type": self.trigger.type,
                                }
                                enqueue_jobs(
                                    self.cache_dir,
                                    sources=[str(item)],
                                    workflow_name=self.trigger.workflow,
                                    params=params,
                                )
                            except Exception as exc:
                                logger.warning("trigger[%s]: enqueue failed: %s", trigger_name, exc)
                self.stop_event.wait(timeout=interval)
        finally:
            conn.close()

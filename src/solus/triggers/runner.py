"""Trigger runner factory — starts one thread per trigger.

The four trigger implementations have been extracted into their own modules:
  - folder_watch.py   (FolderWatchTrigger)
  - rss_poll.py       (RssPollTrigger)
  - cron.py           (CronTrigger, _cron_matches)
  - email_poll.py     (EmailPollTrigger)
  - _state.py         (shared state DB helpers)

This module re-exports all public names for backward compatibility and
provides the ``run_triggers()`` factory function.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .spec import Trigger

# Re-exports for backward compatibility
from ._state import (  # noqa: F401
    _STATE_DB_PATH,
    _STATE_SCHEMA,
    _default_state_db_path,
    _is_seen,
    _mark_seen,
    _state_db,
)
from .folder_watch import FolderWatchTrigger  # noqa: F401
from .rss_poll import RssPollTrigger  # noqa: F401
from .cron import CronTrigger, _cron_matches  # noqa: F401
from .email_poll import EmailPollTrigger  # noqa: F401

logger = logging.getLogger(__name__)


def run_triggers(
    cache_dir: Path,
    triggers: list[Trigger],
    *,
    stop_event: threading.Event,
    state_db_path: Path | None = None,
    config=None,
) -> list[threading.Thread]:
    """Start one thread per trigger. Returns the started threads."""
    resolved_state_db = (state_db_path or _default_state_db_path(cache_dir)).expanduser()
    threads: list[threading.Thread] = []
    for trigger in triggers:
        if not trigger.enabled:
            logger.info("trigger[%s]: disabled; skipping", trigger.name)
            continue
        if trigger.type == "folder_watch":
            runner: FolderWatchTrigger | RssPollTrigger | CronTrigger | EmailPollTrigger = FolderWatchTrigger(
                trigger, cache_dir, resolved_state_db, stop_event
            )
        elif trigger.type == "rss_poll":
            runner = RssPollTrigger(trigger, cache_dir, resolved_state_db, stop_event, config=config)
        elif trigger.type == "cron":
            runner = CronTrigger(trigger, cache_dir, resolved_state_db, stop_event)
        elif trigger.type == "email_poll":
            runner = EmailPollTrigger(trigger, cache_dir, resolved_state_db, stop_event)
        else:
            logger.warning("Unknown trigger type: %s (trigger=%s)", trigger.type, trigger.name)
            continue
        t = threading.Thread(target=runner.run, name=f"trigger-{trigger.name}", daemon=True)
        t.start()
        threads.append(t)
    return threads

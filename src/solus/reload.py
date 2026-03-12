"""
Hot-reload system for Solus.

Watches modules.d/, workflows.d/, and triggers.d/ directories for changes
and reloads modules/workflows when files are modified.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class WatchedPath:
    path: Path
    last_mtime: float = 0.0


class FileWatcher:
    """Polls a list of directories every N seconds for file changes."""

    def __init__(
        self, dirs: list[Path], interval: float = 5.0, extensions: tuple[str, ...] = (".py", ".yaml", ".yml")
    ) -> None:
        self.dirs = dirs
        self.interval = interval
        self.extensions = extensions
        self._mtimes: dict[str, float] = {}
        self._initialize()

    def _initialize(self) -> None:
        for d in self.dirs:
            resolved = d.expanduser()
            if not resolved.is_dir():
                continue
            for f in resolved.rglob("*"):
                if f.is_file() and f.suffix in self.extensions:
                    try:
                        self._mtimes[str(f)] = f.stat().st_mtime
                    except OSError:
                        pass

    def check(self) -> bool:
        """Return True if any watched file changed since last check."""
        changed = False
        seen: set[str] = set()

        for d in self.dirs:
            resolved = d.expanduser()
            if not resolved.is_dir():
                continue
            for f in resolved.rglob("*"):
                if not f.is_file() or f.suffix not in self.extensions:
                    continue
                key = str(f)
                seen.add(key)
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                if self._mtimes.get(key) != mtime:
                    self._mtimes[key] = mtime
                    logger.debug("file changed: %s", f)
                    changed = True

        # Detect deletions
        for key in list(self._mtimes):
            if key not in seen:
                del self._mtimes[key]
                changed = True

        return changed


class HotReloader:
    """
    Watches modules, workflows, and triggers directories for changes.
    On change: reloads modules and clears workflow loader caches.
    Runs in a background daemon thread inside the worker process.
    """

    def __init__(
        self,
        modules_dir: Path | None = None,
        workflows_dir: Path | None = None,
        triggers_dir: Path | None = None,
        interval: float = 5.0,
        on_reload: Callable[[], None] | None = None,
    ) -> None:
        watch_dirs: list[Path] = []
        self._modules_dir: Path | None = None
        if modules_dir:
            watch_dirs.append(modules_dir)
            self._modules_dir = modules_dir.expanduser().resolve()
        if workflows_dir:
            watch_dirs.append(workflows_dir)
        if triggers_dir:
            watch_dirs.append(triggers_dir)

        self._watcher = FileWatcher(watch_dirs, interval=interval)
        self._interval = interval
        self._on_reload = on_reload
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _reload(self) -> None:
        logger.info("hot-reload: change detected, reloading modules and workflows")
        try:
            from .modules.discovery import discover_modules
            from .workflows.registry import global_registry

            # Re-register all modules
            specs = discover_modules(external_dir=self._modules_dir)
            for spec in specs:
                global_registry.register(spec.step_type, spec.handler, spec=spec)
                for alias in spec.aliases:
                    global_registry.register(alias, spec.handler, spec=spec)
            logger.info("hot-reload: registered %d module(s)", len(specs))
        except Exception as exc:
            logger.warning("hot-reload: failed to reload modules: %s", exc)

        if self._on_reload:
            try:
                self._on_reload()
            except Exception as exc:
                logger.warning("hot-reload: on_reload callback failed: %s", exc)

    def _run(self) -> None:
        logger.info("hot-reload: watching for changes (interval=%.1fs)", self._interval)
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._interval)
            if self._stop_event.is_set():
                break
            if self._watcher.check():
                self._reload()

    def start(self) -> None:
        """Start the hot-reload thread."""
        self._thread = threading.Thread(target=self._run, name="hot-reloader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the hot-reload thread to stop."""
        self._stop_event.set()

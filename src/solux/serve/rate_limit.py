from __future__ import annotations

import threading
import time


class WebhookRateLimiter:
    """Sliding-window per-IP rate limiter (max N requests per 60 seconds)."""

    _WINDOW_SECONDS = 60.0
    _COMPACTION_INTERVAL_SECONDS = 15.0

    def __init__(self, max_per_minute: int = 60, *, max_tracked_ips: int = 10_000) -> None:
        self._max = max(1, int(max_per_minute))
        self._max_tracked_ips = max(1, int(max_tracked_ips))
        self._lock = threading.Lock()
        self._timestamps: dict[str, list[float]] = {}
        self._last_compaction = 0.0

    def _compact(self, cutoff: float) -> None:
        for ip, ts in list(self._timestamps.items()):
            kept = [t for t in ts if t > cutoff]
            if kept:
                self._timestamps[ip] = kept
            else:
                del self._timestamps[ip]

    def _evict_oldest_ips(self, overflow: int) -> None:
        if overflow <= 0 or not self._timestamps:
            return
        oldest_first = sorted(
            self._timestamps,
            key=lambda ip: self._timestamps[ip][-1] if self._timestamps[ip] else -1.0,
        )
        for ip in oldest_first[:overflow]:
            self._timestamps.pop(ip, None)

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._WINDOW_SECONDS
        with self._lock:
            if (now - self._last_compaction) >= self._COMPACTION_INTERVAL_SECONDS:
                self._compact(cutoff)
                self._last_compaction = now

            timestamps = [t for t in self._timestamps.get(ip, []) if t > cutoff]
            if len(timestamps) >= self._max:
                self._timestamps[ip] = timestamps
                return False
            timestamps.append(now)
            self._timestamps[ip] = timestamps
            overflow = len(self._timestamps) - self._max_tracked_ips
            if overflow > 0:
                self._evict_oldest_ips(overflow)
            return True

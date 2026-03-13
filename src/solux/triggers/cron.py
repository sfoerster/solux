"""CronTrigger — fires on a cron schedule or fixed interval."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..queueing import enqueue_jobs
from .spec import Trigger
from ._state import _state_db, _is_seen, _mark_seen

logger = logging.getLogger(__name__)


def _cron_matches(schedule: str, dt: datetime) -> bool:
    """Parse a 5-field cron expression and return True if it matches dt."""
    fields = schedule.strip().split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    # Cron day-of-week uses Sunday=0 (or 7), Monday=1 ... Saturday=6.
    cron_dow = (dt.weekday() + 1) % 7
    values = [dt.minute, dt.hour, dt.day, dt.month, cron_dow]
    maxvals = [59, 23, 31, 12, 7]

    def _matches_field(field: str, val: int, max_val: int, *, is_dow: bool = False) -> bool:
        def _parse_num(raw: str) -> int | None:
            try:
                num = int(raw)
            except ValueError:
                return None
            if is_dow and num == 7:
                return 0
            return num

        if field == "*":
            return True
        if field.startswith("*/"):
            try:
                step = int(field[2:])
                if step <= 0:
                    return False
                return val % step == 0
            except ValueError:
                return False
        if "," in field:
            return any(_matches_field(f.strip(), val, max_val, is_dow=is_dow) for f in field.split(","))
        if "-" in field:
            parts = field.split("-")
            if len(parts) != 2:
                return False
            start = _parse_num(parts[0].strip())
            end = _parse_num(parts[1].strip())
            if start is None or end is None:
                return False
            if start <= end:
                return start <= val <= end
            # Wrap-around ranges like 5-0 (Fri..Sun) for day-of-week.
            if is_dow:
                return val >= start or val <= end
            return False
        target = _parse_num(field.strip())
        if target is None:
            return False
        if target < 0 or target > max_val:
            return False
        return target == val

    return all(_matches_field(f, v, m, is_dow=(idx == 4)) for idx, (f, v, m) in enumerate(zip(fields, values, maxvals)))


class CronTrigger:
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
        schedule = str(cfg.get("schedule", "")).strip()
        interval_seconds = cfg.get("interval_seconds")
        trigger_name = self.trigger.name

        if not schedule and interval_seconds is None:
            logger.error("trigger[%s]: cron requires 'schedule' or 'interval_seconds'", trigger_name)
            return

        conn = _state_db(self.state_db_path)
        logger.info("trigger[%s]: cron schedule=%r interval=%s", trigger_name, schedule, interval_seconds)

        last_fired_minute: str = ""
        try:
            while not self.stop_event.is_set():
                now = datetime.now(timezone.utc)
                should_fire = False

                if interval_seconds is not None:
                    interval = float(interval_seconds)
                    key = f"last_fired_{trigger_name}"
                    row = conn.execute(
                        "SELECT seen_at FROM trigger_state WHERE trigger_name=? AND item_key=?",
                        (trigger_name, key),
                    ).fetchone()
                    if row is None:
                        should_fire = True
                    else:
                        from datetime import datetime as _dt

                        try:
                            last_time = _dt.fromisoformat(row[0])
                            should_fire = (now - last_time).total_seconds() >= interval
                        except (ValueError, TypeError):
                            should_fire = True
                    if should_fire:
                        _mark_seen(conn, trigger_name, key)
                        now_str = now.isoformat()
                        conn.execute(
                            "UPDATE trigger_state SET seen_at=? WHERE trigger_name=? AND item_key=?",
                            (now_str, trigger_name, key),
                        )
                        conn.commit()
                elif schedule:
                    minute_key = now.strftime("%Y-%m-%dT%H:%M")
                    if minute_key != last_fired_minute and _cron_matches(schedule, now):
                        if not _is_seen(conn, trigger_name, minute_key):
                            should_fire = True
                            last_fired_minute = minute_key
                            _mark_seen(conn, trigger_name, minute_key)

                if should_fire:
                    logger.info("trigger[%s]: firing cron", trigger_name)
                    try:
                        params = {
                            **dict(self.trigger.params),
                            "_trigger_name": trigger_name,
                            "_trigger_type": self.trigger.type,
                        }
                        enqueue_jobs(
                            self.cache_dir,
                            sources=[self.trigger.workflow],
                            workflow_name=self.trigger.workflow,
                            params=params,
                        )
                    except Exception as exc:
                        logger.warning("trigger[%s]: enqueue failed: %s", trigger_name, exc)

                self.stop_event.wait(timeout=30)
        finally:
            conn.close()

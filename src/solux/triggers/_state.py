"""Shared state DB helpers for trigger deduplication."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_STATE_DB_PATH = Path("~/.local/share/solux/trigger_state.db")

_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trigger_state (
    trigger_name TEXT NOT NULL,
    item_key     TEXT NOT NULL,
    seen_at      TEXT NOT NULL,
    PRIMARY KEY (trigger_name, item_key)
);
"""


def _state_db(state_db_path: Path) -> sqlite3.Connection:
    state_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(state_db_path), timeout=10, check_same_thread=False)
    conn.executescript(_STATE_SCHEMA)
    conn.commit()
    return conn


def _default_state_db_path(cache_dir: Path) -> Path:
    return cache_dir / "triggers" / "trigger_state.db"


def _is_seen(conn: sqlite3.Connection, trigger_name: str, item_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM trigger_state WHERE trigger_name=? AND item_key=?",
        (trigger_name, item_key),
    ).fetchone()
    return row is not None


def _mark_seen(conn: sqlite3.Connection, trigger_name: str, item_key: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO trigger_state (trigger_name, item_key, seen_at) VALUES (?,?,?)",
        (trigger_name, item_key, now),
    )
    conn.commit()

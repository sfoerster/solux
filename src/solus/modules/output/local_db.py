from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from solus.modules.spec import ConfigField, ContextKey, ModuleSpec
from solus.workflows.models import Context, Step

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_sql_identifier(value: str, *, label: str) -> str:
    if not _SAFE_IDENTIFIER_RE.fullmatch(value):
        raise RuntimeError(
            f"output.local_db: invalid {label} {value!r}. "
            "Use only letters, numbers, and underscores, starting with a letter/underscore."
        )
    return value


def _ensure_table(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {table} (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id  TEXT,
            source     TEXT,
            created_at TEXT NOT NULL,
            content    TEXT,
            metadata   TEXT
        );"""
    )


def handle(ctx: Context, step: Step) -> Context:
    db_path = Path(str(step.config.get("db_path", "~/.local/share/solus/records.db"))).expanduser()
    table = _validate_sql_identifier(str(step.config.get("table", "records")), label="table name")
    input_key = str(step.config.get("input_key", "output_text"))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_table(conn, table)
        conn.commit()

        content = ctx.data.get(input_key)
        metadata = {k: v for k, v in ctx.data.items() if k != input_key}
        now = datetime.now(timezone.utc).isoformat()

        cursor = conn.execute(
            f"INSERT INTO {table} (source_id, source, created_at, content, metadata) VALUES (?,?,?,?,?)",  # noqa: S608
            (
                ctx.source_id,
                ctx.source,
                now,
                str(content) if content is not None else None,
                json.dumps(metadata, default=str),
            ),
        )
        conn.commit()
        row_id = cursor.lastrowid
    finally:
        conn.close()

    ctx.data["db_record_id"] = row_id
    ctx.logger.info("local_db: inserted record id=%s into %s", row_id, db_path)
    return ctx


MODULE = ModuleSpec(
    name="local_db",
    version="0.1.0",
    category="output",
    description="Write context data to a local SQLite database.",
    handler=handle,
    config_schema=(
        ConfigField(
            name="db_path", description="Path to SQLite database file", default="~/.local/share/solus/records.db"
        ),
        ConfigField(name="table", description="Table name", default="records"),
        ConfigField(name="input_key", description="Context key to store as content", default="output_text"),
    ),
    reads=(ContextKey("output_text", "Content to store (configurable via input_key)"),),
    writes=(ContextKey("db_record_id", "Inserted row ID"),),
    safety="trusted_only",
)

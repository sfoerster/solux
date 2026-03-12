"""Tests for the trigger system (triggers/ package)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

from solus.triggers.loader import load_triggers
from solus.triggers.spec import Trigger


# ---------------------------------------------------------------------------
# Trigger YAML loading
# ---------------------------------------------------------------------------


def _write_trigger(triggers_dir: Path, filename: str, content: dict) -> Path:
    f = triggers_dir / filename
    f.write_text(yaml.dump(content), encoding="utf-8")
    return f


def test_load_triggers_empty_dir(tmp_path: Path) -> None:
    triggers_dir = tmp_path / "triggers.d"
    triggers_dir.mkdir()
    triggers, errors = load_triggers(triggers_dir)
    assert triggers == []
    assert errors == []


def test_load_triggers_nonexistent_dir(tmp_path: Path) -> None:
    triggers, errors = load_triggers(tmp_path / "no_such_dir")
    assert triggers == []
    assert errors == []


def test_load_trigger_folder_watch(tmp_path: Path) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    _write_trigger(
        td,
        "watch.yaml",
        {
            "name": "watch_podcasts",
            "type": "folder_watch",
            "workflow": "audio_summary",
            "params": {"mode": "full"},
            "config": {"path": "~/Downloads/podcasts", "pattern": "*.mp3", "interval": 30},
        },
    )

    triggers, errors = load_triggers(td)
    assert errors == []
    assert len(triggers) == 1
    t = triggers[0]
    assert t.name == "watch_podcasts"
    assert t.type == "folder_watch"
    assert t.workflow == "audio_summary"
    assert t.params == {"mode": "full"}
    assert t.config["pattern"] == "*.mp3"
    assert t.config["interval"] == 30


def test_load_trigger_rss_poll(tmp_path: Path) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    _write_trigger(
        td,
        "rss.yaml",
        {
            "name": "my_rss",
            "type": "rss_poll",
            "workflow": "webpage_summary",
            "config": {"url": "http://feeds.example.com/rss", "interval": 60},
        },
    )

    triggers, errors = load_triggers(td)
    assert errors == []
    assert len(triggers) == 1
    t = triggers[0]
    assert t.type == "rss_poll"
    assert t.config["url"] == "http://feeds.example.com/rss"


def test_load_trigger_interpolates_env_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    monkeypatch.setenv("TEST_TRIGGER_USER", "user@example.com")
    _write_trigger(
        td,
        "env.yaml",
        {
            "name": "imap_trigger",
            "type": "email_poll",
            "workflow": "email_digest",
            "config": {"username": "${env:TEST_TRIGGER_USER}", "password": "${env:MISSING_TRIGGER_PASS}"},
        },
    )
    triggers, errors = load_triggers(td)
    assert errors == []
    assert len(triggers) == 1
    assert triggers[0].config["username"] == "user@example.com"
    assert triggers[0].config["password"] == ""


def test_load_trigger_multiple_files(tmp_path: Path) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    _write_trigger(
        td,
        "a.yaml",
        {
            "name": "trigger_a",
            "type": "folder_watch",
            "workflow": "audio_summary",
            "config": {"path": "/tmp"},
        },
    )
    _write_trigger(
        td,
        "b.yaml",
        {
            "name": "trigger_b",
            "type": "rss_poll",
            "workflow": "webpage_summary",
            "config": {"url": "http://example.com/rss"},
        },
    )

    triggers, errors = load_triggers(td)
    assert errors == []
    assert len(triggers) == 2
    names = {t.name for t in triggers}
    assert names == {"trigger_a", "trigger_b"}


def test_load_trigger_missing_name_error(tmp_path: Path) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    _write_trigger(
        td,
        "bad.yaml",
        {
            "type": "folder_watch",
            "workflow": "audio_summary",
            "config": {"path": "/tmp"},
        },
    )

    triggers, errors = load_triggers(td)
    assert triggers == []
    assert len(errors) == 1
    assert "missing 'name'" in errors[0]


def test_load_trigger_missing_workflow_error(tmp_path: Path) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    _write_trigger(
        td,
        "bad.yaml",
        {
            "name": "broken",
            "type": "folder_watch",
            "config": {"path": "/tmp"},
        },
    )

    triggers, errors = load_triggers(td)
    assert triggers == []
    assert len(errors) == 1
    assert "missing 'workflow'" in errors[0]


def test_load_trigger_unknown_type_error(tmp_path: Path) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    _write_trigger(
        td,
        "bad.yaml",
        {
            "name": "bad_type",
            "type": "email_watch",
            "workflow": "audio_summary",
            "config": {},
        },
    )

    triggers, errors = load_triggers(td)
    assert triggers == []
    assert len(errors) == 1
    assert "unknown type" in errors[0]


def test_load_trigger_invalid_yaml_error(tmp_path: Path) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    (td / "bad.yaml").write_text(": invalid: yaml: [\n", encoding="utf-8")

    triggers, errors = load_triggers(td)
    assert triggers == []
    assert len(errors) == 1


def test_load_trigger_skips_errors_loads_valid(tmp_path: Path) -> None:
    td = tmp_path / "triggers.d"
    td.mkdir()
    _write_trigger(td, "bad.yaml", {"name": "broken", "type": "unknown", "workflow": "x", "config": {}})
    _write_trigger(
        td,
        "good.yaml",
        {
            "name": "good_trigger",
            "type": "folder_watch",
            "workflow": "audio_summary",
            "config": {"path": "/tmp"},
        },
    )

    triggers, errors = load_triggers(td)
    assert len(triggers) == 1
    assert triggers[0].name == "good_trigger"
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Trigger spec dataclass
# ---------------------------------------------------------------------------


def test_trigger_is_frozen() -> None:
    t = Trigger(name="t", type="folder_watch", workflow="w", params={}, config={})
    with pytest.raises((AttributeError, TypeError)):
        t.name = "new_name"  # type: ignore[misc]


def test_trigger_defaults_empty_params() -> None:
    t = Trigger(name="t", type="rss_poll", workflow="w", params={}, config={"url": "http://x.com"})
    assert t.params == {}


# ---------------------------------------------------------------------------
# FolderWatchTrigger state tracking
# ---------------------------------------------------------------------------


def test_folder_watch_trigger_detects_new_files(tmp_path: Path) -> None:
    """Test FolderWatchTrigger detects new files and tracks state to avoid re-enqueue."""
    import threading
    from unittest.mock import patch

    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    state_db = tmp_path / "state.db"

    trigger = Trigger(
        name="test_watch",
        type="folder_watch",
        workflow="audio_summary",
        params={"mode": "full"},
        config={"path": str(watch_dir), "pattern": "*.mp3", "interval": 0.05},
    )

    enqueued = []
    stop_event = threading.Event()

    def mock_enqueue(cache_dir, sources, workflow_name=None, params=None):
        enqueued.extend(sources)
        return [{"job_id": f"job_{s}"} for s in sources]

    from solus.triggers.runner import FolderWatchTrigger, _state_db, _is_seen, _mark_seen

    # Test state DB tracking directly
    conn = _state_db(state_db)

    # Add a file and test the state tracking logic
    (watch_dir / "ep1.mp3").write_text("audio")
    file_key = str((watch_dir / "ep1.mp3").resolve())

    assert not _is_seen(conn, "test_watch", file_key)
    _mark_seen(conn, "test_watch", file_key)
    assert _is_seen(conn, "test_watch", file_key)

    # ep2 is new
    (watch_dir / "ep2.mp3").write_text("audio")
    file_key2 = str((watch_dir / "ep2.mp3").resolve())
    assert not _is_seen(conn, "test_watch", file_key2)

    conn.close()


def test_folder_watch_trigger_runs_and_enqueues(tmp_path: Path) -> None:
    """Test FolderWatchTrigger run() picks up new files and enqueues them."""
    import threading
    from unittest.mock import patch

    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    state_db = tmp_path / "state.db"

    (watch_dir / "ep1.mp3").write_text("audio")

    trigger = Trigger(
        name="run_test",
        type="folder_watch",
        workflow="audio_summary",
        params={},
        config={"path": str(watch_dir), "pattern": "*.mp3", "interval": 100},
    )

    enqueued = []
    stop_event = threading.Event()

    def mock_enqueue(cache_dir, sources, workflow_name=None, params=None):
        enqueued.extend(sources)
        stop_event.set()  # Stop after first enqueue
        return []

    from solus.triggers.folder_watch import FolderWatchTrigger

    t = FolderWatchTrigger(trigger, tmp_path, state_db, stop_event)
    with patch("solus.triggers.folder_watch.enqueue_jobs", side_effect=mock_enqueue):
        thread = threading.Thread(target=t.run, daemon=True)
        thread.start()
        thread.join(timeout=2.0)

    assert any("ep1.mp3" in s for s in enqueued)


def test_folder_watch_trigger_pattern_filter(tmp_path: Path) -> None:
    """Test that FolderWatchTrigger respects the file pattern filter."""
    import threading
    from unittest.mock import patch

    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    state_db = tmp_path / "state.db"

    (watch_dir / "ep1.mp3").write_text("audio")
    (watch_dir / "notes.txt").write_text("text")

    trigger = Trigger(
        name="pattern_test",
        type="folder_watch",
        workflow="audio_summary",
        params={},
        config={"path": str(watch_dir), "pattern": "*.mp3", "interval": 100},
    )

    enqueued = []
    stop_event = threading.Event()

    def mock_enqueue(cache_dir, sources, workflow_name=None, params=None):
        enqueued.extend(sources)
        stop_event.set()
        return []

    from solus.triggers.folder_watch import FolderWatchTrigger

    t = FolderWatchTrigger(trigger, tmp_path, state_db, stop_event)
    with patch("solus.triggers.folder_watch.enqueue_jobs", side_effect=mock_enqueue):
        thread = threading.Thread(target=t.run, daemon=True)
        thread.start()
        thread.join(timeout=2.0)

    assert any("ep1.mp3" in s for s in enqueued)
    assert not any("notes.txt" in s for s in enqueued)


def test_folder_watch_trigger_skips_symlink_outside_watch_dir(tmp_path: Path) -> None:
    """Symlinks that resolve outside the watch directory must be silently skipped (H1)."""
    import threading
    from unittest.mock import patch

    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.mp3"
    outside_file.write_text("secret audio")
    # Create a symlink inside watch_dir that points outside
    (watch_dir / "escape.mp3").symlink_to(outside_file)

    state_db = tmp_path / "state.db"
    trigger = Trigger(
        name="symlink_test",
        type="folder_watch",
        workflow="audio_summary",
        params={},
        config={"path": str(watch_dir), "pattern": "*.mp3", "interval": 100},
    )

    enqueued = []
    stop_event = threading.Event()

    def mock_enqueue(cache_dir, sources, workflow_name=None, params=None):
        enqueued.extend(sources)
        stop_event.set()
        return []

    from solus.triggers.folder_watch import FolderWatchTrigger

    t = FolderWatchTrigger(trigger, tmp_path, state_db, stop_event)
    # Run one iteration then stop
    stop_event.set()
    with patch("solus.triggers.folder_watch.enqueue_jobs", side_effect=mock_enqueue):
        t.run()

    # The symlink escape.mp3 resolves outside watch_dir → must NOT be enqueued
    assert enqueued == [], f"Expected no enqueues, got: {enqueued}"

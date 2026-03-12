"""Tests for Phase 10: Trigger system expansion."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from solus.triggers.loader import VALID_TYPES, load_triggers
from solus.triggers.runner import _cron_matches, CronTrigger, EmailPollTrigger
from solus.triggers.spec import Trigger


def _make_trigger(t_type: str, config: dict | None = None) -> Trigger:
    return Trigger(
        name=f"test-{t_type}",
        type=t_type,
        workflow="test_workflow",
        params={},
        config=dict(config or {}),
    )


# --- VALID_TYPES includes new types ---


def test_valid_types_includes_cron() -> None:
    assert "cron" in VALID_TYPES


def test_valid_types_includes_email_poll() -> None:
    assert "email_poll" in VALID_TYPES


def test_valid_types_still_has_existing() -> None:
    assert "folder_watch" in VALID_TYPES
    assert "rss_poll" in VALID_TYPES


# --- _cron_matches ---


def test_cron_matches_every_minute() -> None:
    dt = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
    assert _cron_matches("* * * * *", dt) is True


def test_cron_matches_specific_minute() -> None:
    dt = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
    assert _cron_matches("30 10 * * *", dt) is True
    assert _cron_matches("31 10 * * *", dt) is False


def test_cron_matches_every_hour() -> None:
    dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
    assert _cron_matches("0 * * * *", dt) is True
    dt2 = datetime(2024, 1, 15, 10, 1, tzinfo=timezone.utc)
    assert _cron_matches("0 * * * *", dt2) is False


def test_cron_matches_step_syntax() -> None:
    dt = datetime(2024, 1, 15, 10, 15, tzinfo=timezone.utc)
    assert _cron_matches("*/15 * * * *", dt) is True
    dt2 = datetime(2024, 1, 15, 10, 16, tzinfo=timezone.utc)
    assert _cron_matches("*/15 * * * *", dt2) is False


def test_cron_matches_list_syntax() -> None:
    dt = datetime(2024, 1, 15, 10, 5, tzinfo=timezone.utc)
    assert _cron_matches("5,10,15 * * * *", dt) is True
    dt2 = datetime(2024, 1, 15, 10, 7, tzinfo=timezone.utc)
    assert _cron_matches("5,10,15 * * * *", dt2) is False


def test_cron_matches_day_of_month() -> None:
    dt = datetime(2024, 1, 15, 0, 0, tzinfo=timezone.utc)
    assert _cron_matches("0 0 15 * *", dt) is True
    dt2 = datetime(2024, 1, 16, 0, 0, tzinfo=timezone.utc)
    assert _cron_matches("0 0 15 * *", dt2) is False


def test_cron_day_of_week_uses_sunday_zero_or_seven() -> None:
    # 2024-01-14 is Sunday UTC.
    sunday = datetime(2024, 1, 14, 8, 0, tzinfo=timezone.utc)
    monday = datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc)
    assert _cron_matches("0 8 * * 0", sunday) is True
    assert _cron_matches("0 8 * * 7", sunday) is True
    assert _cron_matches("0 8 * * 0", monday) is False


def test_cron_invalid_field_count() -> None:
    dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
    assert _cron_matches("* * *", dt) is False
    assert _cron_matches("", dt) is False


# --- CronTrigger class ---


def test_cron_trigger_interval(tmp_path: Path) -> None:
    from solus.triggers.runner import _STATE_DB_PATH

    trigger = _make_trigger("cron", {"interval_seconds": 1})
    stop = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state_db = tmp_path / "state.db"
    ct = CronTrigger(trigger, cache_dir, state_db, stop)
    fired = []

    with patch("solus.triggers.cron.enqueue_jobs") as mock_enqueue:
        mock_enqueue.side_effect = lambda *a, **kw: fired.append(True)
        t = threading.Thread(target=ct.run, daemon=True)
        t.start()
        time.sleep(0.2)
        stop.set()
        t.join(timeout=3)
    # At least one fire should have occurred
    assert len(fired) >= 1


def test_cron_trigger_schedule_no_match(tmp_path: Path) -> None:
    # Use a cron schedule that won't match current time (minute=61 is impossible)
    trigger = _make_trigger("cron", {"schedule": "61 * * * *"})
    stop = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state_db = tmp_path / "state.db"
    ct = CronTrigger(trigger, cache_dir, state_db, stop)
    fired = []

    with patch("solus.triggers.cron.enqueue_jobs") as mock_enqueue:
        mock_enqueue.side_effect = lambda *a, **kw: fired.append(True)
        t = threading.Thread(target=ct.run, daemon=True)
        t.start()
        time.sleep(0.1)
        stop.set()
        t.join(timeout=3)
    assert len(fired) == 0


def test_cron_trigger_no_config_exits_cleanly(tmp_path: Path) -> None:
    trigger = _make_trigger("cron")  # No schedule or interval_seconds
    stop = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state_db = tmp_path / "state.db"
    ct = CronTrigger(trigger, cache_dir, state_db, stop)
    t = threading.Thread(target=ct.run, daemon=True)
    t.start()
    t.join(timeout=2)
    assert not t.is_alive()


# --- EmailPollTrigger class ---


def test_email_poll_trigger_no_creds_exits(tmp_path: Path) -> None:
    trigger = _make_trigger("email_poll")  # Missing creds
    stop = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state_db = tmp_path / "state.db"
    ept = EmailPollTrigger(trigger, cache_dir, state_db, stop)
    t = threading.Thread(target=ept.run, daemon=True)
    t.start()
    t.join(timeout=2)
    assert not t.is_alive()


def test_email_poll_trigger_retries_when_enqueue_fails(tmp_path: Path) -> None:
    trigger = _make_trigger(
        "email_poll",
        {
            "host": "imap.example.com",
            "username": "user",
            "password": "pass",
            "interval_seconds": 0.01,
        },
    )
    stop = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state_db = tmp_path / "state.db"
    ept = EmailPollTrigger(trigger, cache_dir, state_db, stop)

    class FakeIMAP:
        def login(self, username: str, password: str) -> None:
            del username, password

        def select(self, folder: str) -> tuple[str, list[bytes]]:
            del folder
            return ("OK", [b""])

        def search(self, charset, criteria):  # noqa: ANN001
            del charset, criteria
            return ("OK", [b"1"])

        def fetch(self, uid, query):  # noqa: ANN001
            del uid, query
            msg = b"Subject: test\r\nFrom: sender@example.com\r\nDate: Thu, 1 Jan 1970 00:00:00 +0000\r\n\r\nBody"
            return ("OK", [(b"1 (RFC822 {0})", msg)])

        def logout(self) -> None:
            return

    enqueue_calls = {"count": 0}

    def _enqueue(*args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        enqueue_calls["count"] += 1
        if enqueue_calls["count"] == 1:
            raise RuntimeError("temporary queue error")
        stop.set()
        return []

    with patch("solus.triggers.email_poll.imaplib.IMAP4_SSL", return_value=FakeIMAP()):
        with patch("solus.triggers.email_poll.enqueue_jobs", side_effect=_enqueue):
            t = threading.Thread(target=ept.run, daemon=True)
            t.start()
            t.join(timeout=1.0)
            if t.is_alive():
                stop.set()
                t.join(timeout=1.0)

    assert enqueue_calls["count"] >= 2


# --- load_triggers validation ---


def test_load_triggers_cron_yaml(tmp_path: Path) -> None:
    import yaml

    trigger_file = tmp_path / "my_cron.yaml"
    trigger_file.write_text(
        yaml.dump(
            {
                "name": "hourly",
                "type": "cron",
                "workflow": "my_workflow",
                "config": {"schedule": "0 * * * *"},
            }
        ),
        encoding="utf-8",
    )
    triggers, errors = load_triggers(tmp_path)
    assert not errors
    assert len(triggers) == 1
    assert triggers[0].type == "cron"
    assert triggers[0].config["schedule"] == "0 * * * *"


def test_load_triggers_email_poll_yaml(tmp_path: Path) -> None:
    import yaml

    trigger_file = tmp_path / "my_email.yaml"
    trigger_file.write_text(
        yaml.dump(
            {
                "name": "inbox",
                "type": "email_poll",
                "workflow": "process_email",
                "config": {
                    "host": "imap.example.com",
                    "username": "user@example.com",
                    "password": "${env:IMAP_PASS}",
                },
            }
        ),
        encoding="utf-8",
    )
    triggers, errors = load_triggers(tmp_path)
    assert not errors
    assert triggers[0].type == "email_poll"


# --- Inbound webhook trigger via serve/api ---


def test_trigger_webhook_api(tmp_path: Path) -> None:
    from solus.serve.api import handle_trigger_webhook
    from unittest.mock import patch

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    mock_wf = MagicMock()
    mock_wf.name = "test_workflow"

    with patch("solus.workflows.loader.load_workflow", return_value=mock_wf):
        with patch("solus.workflows.registry.build_registry", return_value=MagicMock()):
            with patch("solus.workflows.validation.validate_workflow") as mock_validate:
                mock_validate.return_value = MagicMock(valid=True, issues=[])
                with patch("solus.serve.api.enqueue_jobs") as mock_enqueue:
                    mock_enqueue.return_value = [{"job_id": "abc123"}]
                    ok, result = handle_trigger_webhook(cache_dir, "test_workflow", {"source": "test"})

    assert ok is True
    assert result["job_id"] == "abc123"
    assert result["status"] == "queued"


def test_trigger_webhook_unknown_workflow(tmp_path: Path) -> None:
    from solus.serve.api import handle_trigger_webhook
    from solus.workflows.loader import WorkflowLoadError

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch("solus.workflows.loader.load_workflow", side_effect=WorkflowLoadError("not found")):
        ok, result = handle_trigger_webhook(cache_dir, "no_such_workflow", {})

    assert ok is False
    assert "not found" in str(result).lower()


# --- run_triggers dispatches new types ---


def test_run_triggers_creates_cron_thread(tmp_path: Path) -> None:
    from solus.triggers.runner import run_triggers

    trigger = _make_trigger("cron", {"interval_seconds": 9999})
    stop = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state_db = tmp_path / "state.db"
    threads = run_triggers(cache_dir, [trigger], stop_event=stop, state_db_path=state_db)
    assert len(threads) == 1
    assert threads[0].is_alive()
    stop.set()
    threads[0].join(timeout=3)


def test_run_triggers_defaults_state_db_to_cache_dir(tmp_path: Path) -> None:
    from solus.triggers.runner import run_triggers

    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    trigger = _make_trigger("folder_watch", {"path": str(watch_dir), "interval": 0.05})
    stop = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    threads = run_triggers(cache_dir, [trigger], stop_event=stop)
    assert len(threads) == 1

    time.sleep(0.05)
    stop.set()
    threads[0].join(timeout=2.0)

    assert (cache_dir / "triggers" / "trigger_state.db").exists()


def test_run_triggers_creates_email_poll_thread(tmp_path: Path) -> None:
    from solus.triggers.runner import run_triggers

    trigger = _make_trigger(
        "email_poll",
        {
            "host": "imap.example.com",
            "username": "u",
            "password": "p",
            "interval_seconds": 9999,
        },
    )
    stop = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state_db = tmp_path / "state.db"

    import imaplib

    with patch.object(imaplib, "IMAP4_SSL") as mock_imap:
        mock_imap.return_value.__enter__ = MagicMock(return_value=MagicMock())
        threads = run_triggers(cache_dir, [trigger], stop_event=stop, state_db_path=state_db)
    assert len(threads) == 1
    stop.set()
    threads[0].join(timeout=3)

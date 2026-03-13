from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import shutil
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..background import ensure_background_worker, start_background_worker, stop_background_worker, worker_status
from ..config import effective_external_modules_dir
from ..queueing import enqueue_jobs, prune_jobs, queue_counts, read_jobs, retry_failed_jobs
from .sources import discover_sources, safe_select_file, safe_select_source

_WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def verify_webhook_signature(
    body: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """Verify an ``X-Solux-Signature: sha256=<hex>`` header against *body*.

    Returns True if the HMAC matches. Uses constant-time comparison.
    """
    if not signature_header.startswith("sha256="):
        return False
    expected_hex = signature_header[7:]
    computed = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, expected_hex)


def _coerce_webhook_source(workflow_name: str, params: dict[str, Any]) -> tuple[bool, str]:
    raw = params.get("source", f"webhook://{workflow_name}")
    if isinstance(raw, (str, int, float, bool)):
        value = str(raw).strip()
        return True, value or f"webhook://{workflow_name}"
    if raw is None:
        return True, f"webhook://{workflow_name}"
    return False, "Invalid 'source' value in webhook payload; expected a string-like scalar"


def _coerce_bool(value: Any, *, field: str) -> tuple[bool, bool | str]:
    if isinstance(value, bool):
        return True, value
    if isinstance(value, int):
        return True, bool(value)
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"1", "true", "yes", "on"}:
            return True, True
        if norm in {"0", "false", "no", "off"}:
            return True, False
    return False, f"Invalid '{field}' value {value!r}; expected boolean"


def handle_worker_status(cache_dir: Path) -> dict[str, Any]:
    return worker_status(cache_dir)


def handle_delete(cache_dir: Path, sid: str) -> tuple[bool, str]:
    if "/" in sid or "\\" in sid or ".." in sid:
        return False, "Invalid sid"
    source_dir = cache_dir / "sources" / sid
    shutil.rmtree(source_dir, ignore_errors=True)
    return True, ""


def handle_rerun(
    cache_dir: Path,
    sid: str,
    mode: str,
    output_format: str,
    *,
    default_workflow: str = "audio_summary",
) -> tuple[bool, str]:
    if "/" in sid or "\\" in sid or ".." in sid:
        return False, "Invalid sid"

    source_dir = cache_dir / "sources" / sid
    meta_path = source_dir / "metadata.json"
    if not meta_path.exists():
        return False, "Source metadata not found"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Failed to read metadata: {exc}"

    source_url = str(meta.get("source", ""))
    if not source_url:
        return False, "No source URL in metadata"

    if mode not in {"transcript", "tldr", "outline", "notes", "full"}:
        mode = "full"
    if output_format not in {"markdown", "text", "json"}:
        output_format = "markdown"

    workflow_name = str(meta.get("workflow_name") or default_workflow)
    enqueue_jobs(
        cache_dir,
        [source_url],
        workflow_name=workflow_name,
        params={
            "mode": mode,
            "format": output_format,
            "timestamps": False,
            "no_cache": True,
        },
    )
    return True, sid


def handle_ingest_url(cache_dir: Path, url: str, mode: str, output_format: str, workflow_name: str) -> bool:
    if mode not in {"transcript", "tldr", "outline", "notes", "full"}:
        mode = "full"
    if output_format not in {"markdown", "text", "json"}:
        output_format = "markdown"
    enqueue_jobs(
        cache_dir,
        [url],
        workflow_name=workflow_name,
        params={
            "mode": mode,
            "format": output_format,
            "timestamps": False,
            "no_cache": False,
        },
    )
    ensure_background_worker(cache_dir)
    return True


def handle_ingest_file(
    cache_dir: Path,
    file_data: bytes,
    file_name: str,
    mode: str,
    output_format: str,
    workflow_name: str,
) -> tuple[bool, str | None]:
    if mode not in {"transcript", "tldr", "outline", "notes", "full"}:
        mode = "full"
    if output_format not in {"markdown", "text", "json"}:
        output_format = "markdown"

    uploads_dir = cache_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", file_name)
    dest = uploads_dir / f"{uuid.uuid4().hex[:12]}-{safe_name}"
    dest.write_bytes(file_data)

    jobs = enqueue_jobs(
        cache_dir,
        [str(dest)],
        workflow_name=workflow_name,
        params={
            "mode": mode,
            "format": output_format,
            "timestamps": False,
            "no_cache": False,
        },
    )
    ensure_background_worker(cache_dir)
    job_id = jobs[0]["job_id"] if jobs else None
    return True, job_id


def handle_worker_start(cache_dir: Path) -> tuple[bool, str]:
    started, pid, reason = start_background_worker(cache_dir, poll_interval=2.0, workers=1)
    if started or reason == "already-running":
        return True, ""
    if reason == "start-failed":
        return False, "Worker failed to start."
    return False, "Could not start worker (lock held)"


def handle_worker_stop(cache_dir: Path) -> tuple[bool, str]:
    stopped, reason = stop_background_worker(cache_dir)
    if stopped or reason == "not-running":
        return True, ""
    if reason == "timeout":
        return False, "timeout"
    return False, reason


def handle_worker_restart(cache_dir: Path) -> tuple[bool, str]:
    ok_stop, stop_reason = handle_worker_stop(cache_dir)
    if not ok_stop:
        return False, stop_reason
    return handle_worker_start(cache_dir)


def handle_list_workflows(workflows_dir: Path | None = None) -> tuple[list[Any], list[str]]:
    from ..workflows.loader import list_workflows

    return list_workflows(workflows_dir)


def handle_save_workflow(
    cache_dir: Path,
    workflows_dir: Path,
    name: str,
    yaml_content: str,
) -> tuple[bool, str]:
    """Validate and save a workflow YAML. Returns (ok, error_message)."""
    from ..workflows.loader import WorkflowLoadError, _parse_workflow

    if not name or not re.match(r"^[\w\-]+$", name):
        return False, f"Invalid workflow name: {name!r} (use only letters, digits, _ and -)"
    try:
        payload = yaml.safe_load(yaml_content)
        _parse_workflow(payload, source=f"<editor:{name}>")
    except yaml.YAMLError as exc:
        return False, f"Invalid YAML: {exc}"
    except WorkflowLoadError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)

    workflows_dir.mkdir(parents=True, exist_ok=True)
    dest = workflows_dir / f"{name}.yaml"
    try:
        dest.write_text(yaml_content, encoding="utf-8")
    except OSError as exc:
        return False, f"Failed to write workflow file: {exc}"
    return True, ""


def handle_trigger_webhook(
    cache_dir: Path,
    workflow_name: str,
    params: dict[str, Any],
    *,
    workflows_dir: Path | None = None,
    config: Any | None = None,
) -> tuple[bool, dict[str, Any] | str]:
    """Enqueue a job for the given workflow triggered by a webhook."""
    from ..workflows.loader import WorkflowLoadError, load_workflow
    from ..workflows.registry import build_registry
    from ..workflows.validation import validate_workflow

    if not _WORKFLOW_NAME_RE.fullmatch(workflow_name):
        return False, "Invalid workflow name"

    try:
        workflow = load_workflow(workflow_name, workflow_dir=workflows_dir)
    except WorkflowLoadError as exc:
        return False, str(exc)

    modules_dir = effective_external_modules_dir(config)
    security_mode = str(getattr(getattr(config, "security", None), "mode", "trusted")).lower()
    registry = build_registry(external_dir=modules_dir)
    validation = validate_workflow(workflow, registry=registry, security_mode=security_mode)
    validation_errors = [issue.message for issue in validation.issues if issue.level == "error"]
    if validation_errors:
        return False, f"Workflow '{workflow_name}' rejected by security validation: {validation_errors[0]}"

    ok_source, source_value = _coerce_webhook_source(workflow_name, params)
    if not ok_source:
        return False, source_value

    jobs = enqueue_jobs(
        cache_dir,
        sources=[source_value],
        workflow_name=workflow_name,
        params=params,
    )
    if jobs:
        return True, {"job_id": jobs[0]["job_id"], "status": "queued"}
    return False, "Failed to enqueue job"


def handle_list_triggers(triggers_dir: Path | None = None) -> tuple[list, list[str]]:
    from ..config import get_default_triggers_dir
    from ..triggers.loader import load_triggers

    resolved = triggers_dir or get_default_triggers_dir()
    return load_triggers(resolved)


def handle_get_trigger_yaml(triggers_dir: Path, name: str) -> str:
    """Return the raw YAML text for a trigger file, or '' if not found."""
    for ext in (".yaml", ".yml"):
        p = triggers_dir / f"{name}{ext}"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def handle_save_trigger(
    triggers_dir: Path,
    name: str,
    yaml_content: str,
) -> tuple[bool, str]:
    """Validate and save a trigger YAML. Returns (ok, error_message)."""
    import yaml as _yaml

    from ..triggers.loader import _parse_trigger

    if not name or not re.match(r"^[\w\-]+$", name):
        return False, f"Invalid trigger name: {name!r} (use only letters, digits, _ and -)"
    try:
        payload = _yaml.safe_load(yaml_content)
    except _yaml.YAMLError as exc:
        return False, f"Invalid YAML: {exc}"
    if not isinstance(payload, dict):
        return False, "Trigger document must be a YAML mapping"
    try:
        _parse_trigger(payload, source=f"<editor:{name}>")
    except ValueError as exc:
        return False, str(exc)

    triggers_dir.mkdir(parents=True, exist_ok=True)
    dest = triggers_dir / f"{name}.yaml"
    try:
        dest.write_text(yaml_content, encoding="utf-8")
    except OSError as exc:
        return False, f"Failed to write trigger file: {exc}"
    return True, ""


def handle_delete_trigger(triggers_dir: Path, name: str) -> tuple[bool, str]:
    if "/" in name or "\\" in name or ".." in name:
        return False, "Invalid trigger name"
    for ext in (".yaml", ".yml"):
        p = triggers_dir / f"{name}{ext}"
        if p.exists():
            p.unlink()
            return True, ""
    return False, f"Trigger '{name}' not found"


def handle_set_trigger_enabled(triggers_dir: Path, name: str, enabled: bool) -> tuple[bool, str]:
    import yaml as _yaml

    from ..triggers.loader import _parse_trigger

    if not name or not re.match(r"^[\w\-]+$", name):
        return False, f"Invalid trigger name: {name!r}"

    trigger_path: Path | None = None
    for ext in (".yaml", ".yml"):
        p = triggers_dir / f"{name}{ext}"
        if p.exists():
            trigger_path = p
            break
    if trigger_path is None:
        return False, f"Trigger '{name}' not found"

    try:
        payload = _yaml.safe_load(trigger_path.read_text(encoding="utf-8"))
    except (_yaml.YAMLError, OSError) as exc:
        return False, f"Failed to read trigger file: {exc}"
    if not isinstance(payload, dict):
        return False, "Trigger document must be a YAML mapping"

    payload["enabled"] = bool(enabled)
    try:
        _parse_trigger(payload, source=f"<toggle:{name}>")
    except ValueError as exc:
        return False, str(exc)

    try:
        trigger_path.write_text(_yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    except OSError as exc:
        return False, f"Failed to write trigger file: {exc}"
    return True, ""


def handle_run_trigger_now(
    cache_dir: Path,
    triggers_dir: Path,
    name: str,
) -> tuple[bool, str]:
    import yaml as _yaml

    from ..triggers.loader import _parse_trigger

    if not name or not re.match(r"^[\w\-]+$", name):
        return False, "Invalid trigger name"
    raw_yaml = handle_get_trigger_yaml(triggers_dir, name)
    if not raw_yaml:
        return False, f"Trigger '{name}' not found"
    try:
        payload = _yaml.safe_load(raw_yaml)
    except _yaml.YAMLError as exc:
        return False, f"Invalid trigger YAML: {exc}"
    if not isinstance(payload, dict):
        return False, "Trigger document must be a YAML mapping"
    try:
        trigger = _parse_trigger(payload, source=f"<run-now:{name}>")
    except ValueError as exc:
        return False, str(exc)

    params = {
        **dict(trigger.params),
        "_trigger_name": trigger.name,
        "_trigger_type": trigger.type,
        "_trigger_manual": True,
    }
    source = f"trigger://{trigger.name}/manual"
    enqueue_jobs(cache_dir, [source], workflow_name=trigger.workflow, params=params)
    ensure_background_worker(cache_dir)
    return True, ""


def trigger_last_seen_by_name(cache_dir: Path) -> dict[str, str]:
    from ..triggers._state import _default_state_db_path

    state_path = _default_state_db_path(cache_dir)
    if not state_path.exists():
        return {}
    try:
        conn = sqlite3.connect(str(state_path))
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            "SELECT trigger_name, MAX(seen_at) AS last_seen FROM trigger_state GROUP BY trigger_name"
        ).fetchall()
        return {str(name): str(last_seen) for name, last_seen in rows if name and last_seen}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def handle_delete_workflow(workflows_dir: Path, name: str) -> tuple[bool, str]:
    if "/" in name or "\\" in name or ".." in name:
        return False, "Invalid workflow name"
    for ext in (".yaml", ".yml"):
        p = workflows_dir / f"{name}{ext}"
        if p.exists():
            p.unlink()
            return True, ""
    return False, f"Workflow '{name}' not found (built-in workflows cannot be deleted)"


def handle_get_config(config_path: Path) -> str:
    """Return the raw TOML text of the config file, or a bootstrap template."""
    if config_path.exists():
        try:
            return config_path.read_text(encoding="utf-8")
        except OSError:
            pass
    from ..config import build_bootstrap_config_toml

    return build_bootstrap_config_toml()


def handle_save_config(config_path: Path, toml_content: str) -> tuple[bool, str]:
    """Validate TOML syntax and write config file. Returns (ok, error_message)."""
    import tomllib

    try:
        tomllib.loads(toml_content)
    except tomllib.TOMLDecodeError as exc:
        return False, f"Invalid TOML: {exc}"
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(toml_content, encoding="utf-8")
    except OSError as exc:
        return False, f"Failed to write config: {exc}"
    return True, ""


def handle_bulk_retry_failed(cache_dir: Path) -> tuple[bool, str]:
    """Reset all failed/dead-letter jobs back to pending."""
    reset = retry_failed_jobs(cache_dir)
    return True, f"Reset {len(reset)} job(s) to pending"


def handle_bulk_clear_dead_letter(cache_dir: Path) -> tuple[bool, str]:
    """Delete all dead_letter jobs from the queue."""
    result = prune_jobs(cache_dir, statuses={"dead_letter"})
    return True, f"Cleared {result['removed']} dead letter job(s)"


def get_index_data(
    cache_dir: Path,
    yt_dlp_binary: str | None,
    sid: str | None,
    file_name: str | None,
    workflow_filter: str | None,
) -> dict[str, Any]:
    entries = discover_sources(cache_dir, yt_dlp_binary=yt_dlp_binary)
    selected_source = safe_select_source(entries, sid)
    selected_file = safe_select_file(selected_source, file_name) if selected_source else None
    q_counts = queue_counts(cache_dir)
    jobs = read_jobs(cache_dir, limit=200, newest_first=True)
    if workflow_filter:
        jobs = [job for job in jobs if str(job.get("workflow_name", "")) == workflow_filter]
    w_stat = worker_status(cache_dir)
    return {
        "entries": entries,
        "selected_source": selected_source,
        "selected_file": selected_file,
        "q_counts": q_counts,
        "jobs": jobs,
        "w_stat": w_stat,
    }

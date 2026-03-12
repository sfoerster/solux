from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from solus.config import get_default_workflows_dir
from solus.modules._helpers import interpolate_env

from .builtins.audio_summary import BUILTIN_WORKFLOWS
from .models import Step, Workflow


def _interpolate_secrets(val: Any, strict: bool = False, warn_missing: bool = True) -> Any:
    """Recursively replace ``${env:VAR_NAME}`` patterns in workflow config structures."""
    if isinstance(val, str):
        return interpolate_env(val, strict=strict, warn_missing=warn_missing)
    if isinstance(val, dict):
        return {k: _interpolate_secrets(v, strict=strict, warn_missing=warn_missing) for k, v in val.items()}
    if isinstance(val, list):
        return [_interpolate_secrets(item, strict=strict, warn_missing=warn_missing) for item in val]
    return val


class WorkflowLoadError(Exception):
    """Raised when workflow YAML cannot be loaded or validated."""


def _parse_step(
    raw: Any,
    index: int,
    strict_secrets: bool = False,
    interpolate_secrets: bool = True,
    warn_missing_secrets: bool = True,
) -> Step:
    if not isinstance(raw, dict):
        raise WorkflowLoadError(f"steps[{index}] must be a mapping")
    name = raw.get("name")
    step_type = raw.get("type")
    cfg = raw.get("config", {})
    if not isinstance(name, str) or not name.strip():
        raise WorkflowLoadError(f"steps[{index}].name must be a non-empty string")
    if not isinstance(step_type, str) or not step_type.strip():
        raise WorkflowLoadError(f"steps[{index}].type must be a non-empty string")
    if not isinstance(cfg, dict):
        raise WorkflowLoadError(f"steps[{index}].config must be a mapping")
    when = raw.get("when", None)
    if when is not None and not isinstance(when, str):
        raise WorkflowLoadError(f"steps[{index}].when must be a string expression")
    foreach = raw.get("foreach", None)
    if foreach is not None and not isinstance(foreach, str):
        raise WorkflowLoadError(f"steps[{index}].foreach must be a string (context key)")
    timeout_raw = raw.get("timeout", None)
    timeout_seconds: int | None = None
    if timeout_raw is not None:
        try:
            timeout_seconds = int(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise WorkflowLoadError(f"steps[{index}].timeout must be an integer") from exc
        if timeout_seconds < 1:
            raise WorkflowLoadError(f"steps[{index}].timeout must be a positive integer (got {timeout_seconds})")
    on_error = raw.get("on_error", None)
    if on_error is not None and not isinstance(on_error, str):
        raise WorkflowLoadError(f"steps[{index}].on_error must be a string (workflow name)")
    config = dict(cfg)
    if interpolate_secrets:
        config = _interpolate_secrets(config, strict=strict_secrets, warn_missing=warn_missing_secrets)

    return Step(
        name=name.strip(),
        type=step_type.strip(),
        config=config,
        when=when.strip() if isinstance(when, str) else None,
        foreach=foreach.strip() if isinstance(foreach, str) else None,
        timeout_seconds=timeout_seconds,
        on_error=on_error.strip() if isinstance(on_error, str) else None,
    )


def _parse_workflow(
    raw: Any,
    *,
    source: str,
    strict_secrets: bool = False,
    interpolate_secrets: bool = True,
    warn_missing_secrets: bool = True,
) -> Workflow:
    if not isinstance(raw, dict):
        raise WorkflowLoadError(f"Workflow document in {source} must be a mapping")
    name = raw.get("name")
    description = raw.get("description", "")
    steps_raw = raw.get("steps")
    if not isinstance(name, str) or not name.strip():
        raise WorkflowLoadError(f"Workflow in {source} must include a non-empty 'name'")
    if not isinstance(description, str):
        raise WorkflowLoadError(f"Workflow '{name}' in {source} has non-string description")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise WorkflowLoadError(f"Workflow '{name}' in {source} must include a non-empty steps list")
    steps = [
        _parse_step(
            item,
            idx,
            strict_secrets=strict_secrets,
            interpolate_secrets=interpolate_secrets,
            warn_missing_secrets=warn_missing_secrets,
        )
        for idx, item in enumerate(steps_raw)
    ]
    return Workflow(name=name.strip(), description=description.strip(), steps=steps)


def _workflow_files(workflow_dir: Path) -> list[Path]:
    if not workflow_dir.exists() or not workflow_dir.is_dir():
        return []
    items = list(workflow_dir.glob("*.yml")) + list(workflow_dir.glob("*.yaml"))
    return sorted(items)


def _load_yaml_file(
    path: Path,
    strict_secrets: bool = False,
    interpolate_secrets: bool = True,
    warn_missing_secrets: bool = True,
) -> Workflow:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkflowLoadError(f"Unable to read workflow file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise WorkflowLoadError(f"Invalid YAML in {path}: {exc}") from exc
    return _parse_workflow(
        payload,
        source=str(path),
        strict_secrets=strict_secrets,
        interpolate_secrets=interpolate_secrets,
        warn_missing_secrets=warn_missing_secrets,
    )


def list_workflows(
    workflow_dir: Path | None = None,
    strict_secrets: bool = False,
    interpolate_secrets: bool = False,
    warn_missing_secrets: bool = False,
) -> tuple[list[Workflow], list[str]]:
    active_dir = workflow_dir or get_default_workflows_dir()
    merged: dict[str, Workflow] = {name: wf for name, wf in BUILTIN_WORKFLOWS.items()}
    invalid: list[str] = []

    for item in _workflow_files(active_dir):
        try:
            wf = _load_yaml_file(
                item,
                strict_secrets=strict_secrets,
                interpolate_secrets=interpolate_secrets,
                warn_missing_secrets=warn_missing_secrets,
            )
        except WorkflowLoadError as exc:
            invalid.append(str(exc))
            continue
        merged[wf.name] = wf

    return sorted(merged.values(), key=lambda wf: wf.name), invalid


def load_workflow(
    name: str,
    workflow_dir: Path | None = None,
    strict_secrets: bool = False,
    warn_missing_secrets: bool = True,
) -> Workflow:
    active_dir = workflow_dir or get_default_workflows_dir()
    load_errors: list[str] = []

    for item in _workflow_files(active_dir):
        try:
            wf = _load_yaml_file(
                item,
                strict_secrets=strict_secrets,
                interpolate_secrets=True,
                warn_missing_secrets=warn_missing_secrets,
            )
        except WorkflowLoadError as exc:
            load_errors.append(str(exc))
            continue
        if wf.name == name or item.stem == name:
            return wf

    builtin = BUILTIN_WORKFLOWS.get(name)
    if builtin:
        return builtin

    available = sorted(set(BUILTIN_WORKFLOWS) | {p.stem for p in _workflow_files(active_dir)})
    suffix = f" Invalid workflow files detected: {len(load_errors)}." if load_errors else ""
    raise WorkflowLoadError(f"Workflow '{name}' not found. Available: {', '.join(available)}.{suffix}")


def workflow_to_dict(workflow: Workflow) -> dict[str, Any]:
    steps = []
    for step in workflow.steps:
        d: dict[str, Any] = {"name": step.name, "type": step.type, "config": step.config}
        if step.when is not None:
            d["when"] = step.when
        if step.foreach is not None:
            d["foreach"] = step.foreach
        if step.timeout_seconds is not None:
            d["timeout"] = step.timeout_seconds
        if step.on_error is not None:
            d["on_error"] = step.on_error
        steps.append(d)
    return {
        "name": workflow.name,
        "description": workflow.description,
        "steps": steps,
    }

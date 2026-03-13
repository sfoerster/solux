from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from .spec import Trigger

logger = logging.getLogger(__name__)

DEFAULT_TRIGGERS_DIR = Path("~/.config/solux/triggers.d")

VALID_TYPES = {"folder_watch", "rss_poll", "cron", "email_poll"}


def _interpolate_secrets(val: Any) -> Any:
    """Replace ${env:VAR_NAME} patterns with environment variable values."""
    if isinstance(val, str):
        return re.sub(
            r"\$\{env:([^}]+)\}",
            lambda m: os.environ.get(m.group(1), ""),
            val,
        )
    if isinstance(val, dict):
        return {k: _interpolate_secrets(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_interpolate_secrets(item) for item in val]
    return val


def _coerce_enabled(value: Any, *, source: str, name: str) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"1", "true", "yes", "on"}:
            return True
        if norm in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Trigger '{name}' in {source} has invalid 'enabled' value {value!r}; expected boolean")


def _parse_trigger(raw: dict, *, source: str) -> Trigger:
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValueError(f"Trigger in {source} missing 'name'")
    trigger_type = str(raw.get("type", "")).strip()
    if trigger_type not in VALID_TYPES:
        raise ValueError(f"Trigger '{name}' in {source} has unknown type '{trigger_type}'; valid: {VALID_TYPES}")
    workflow = str(raw.get("workflow", "")).strip()
    if not workflow:
        raise ValueError(f"Trigger '{name}' in {source} missing 'workflow'")
    params_raw = raw.get("params", {})
    config_raw = raw.get("config", {})
    if not isinstance(params_raw, dict):
        raise ValueError(f"Trigger '{name}' in {source} has non-mapping 'params'")
    if not isinstance(config_raw, dict):
        raise ValueError(f"Trigger '{name}' in {source} has non-mapping 'config'")
    params = _interpolate_secrets(dict(params_raw))
    config = _interpolate_secrets(dict(config_raw))
    enabled = _coerce_enabled(raw.get("enabled"), source=source, name=name)
    return Trigger(name=name, type=trigger_type, workflow=workflow, params=params, config=config, enabled=enabled)


def load_triggers(triggers_dir: Path | None = None) -> tuple[list[Trigger], list[str]]:
    """Scan triggers.d directory and return (valid_triggers, error_strings)."""
    resolved = (triggers_dir or DEFAULT_TRIGGERS_DIR).expanduser().resolve()
    if not resolved.is_dir():
        return [], []

    triggers: list[Trigger] = []
    errors: list[str] = []

    for yaml_file in sorted(resolved.glob("*.yaml")) + sorted(resolved.glob("*.yml")):
        try:
            payload = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{yaml_file}: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{yaml_file}: expected a mapping at top level")
            continue
        try:
            trigger = _parse_trigger(payload, source=str(yaml_file))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        triggers.append(trigger)

    return triggers, errors

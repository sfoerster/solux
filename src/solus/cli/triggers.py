"""CLI commands for managing triggers (``solus triggers``)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from ..config import ConfigError, load_config
from ..triggers.loader import _parse_trigger
from ..workflows.examples import TRIGGER_EXAMPLES


def cmd_triggers_list() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    from ..triggers.loader import load_triggers

    triggers, errors = load_triggers(config.triggers_dir)

    if not triggers:
        print(f"No triggers found in {config.triggers_dir}")
        print("Tip: create a YAML file there or use `solus triggers examples` for templates.")
    for t in triggers:
        print(f"- {t.name}  [{t.type}]  → {t.workflow}")

    if errors:
        print("\nInvalid trigger definitions:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
    return 0


def cmd_triggers_show(name: str) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    triggers_dir = config.triggers_dir
    for ext in (".yaml", ".yml"):
        p = triggers_dir / f"{name}{ext}"
        if p.exists():
            print(p.read_text(encoding="utf-8").rstrip())
            return 0

    print(f"No trigger file found for '{name}' in {triggers_dir}.", file=sys.stderr)
    return 1


def cmd_triggers_validate(name: str) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    triggers_dir = config.triggers_dir
    found: Path | None = None
    for ext in (".yaml", ".yml"):
        p = triggers_dir / f"{name}{ext}"
        if p.exists():
            found = p
            break

    if found is None:
        print(f"No trigger file found for '{name}' in {triggers_dir}.", file=sys.stderr)
        return 1

    try:
        raw = yaml.safe_load(found.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"INVALID — YAML parse error: {exc}", file=sys.stderr)
        return 1

    if not isinstance(raw, dict):
        print("INVALID — top-level document must be a mapping.", file=sys.stderr)
        return 1

    try:
        trigger = _parse_trigger(raw, source=str(found))
    except ValueError as exc:
        print(f"INVALID — {exc}", file=sys.stderr)
        return 1

    # Also check whether the referenced workflow exists.
    from ..workflows.loader import WorkflowLoadError, load_workflow

    try:
        load_workflow(trigger.workflow, workflow_dir=config.workflows_dir)
        wf_note = f"found in {config.workflows_dir}"
        wf_ok = True
    except WorkflowLoadError:
        wf_ok = False
        wf_note = f"missing in {config.workflows_dir}"

    print(f"Trigger : {trigger.name}")
    print(f"  Type    : {trigger.type}")
    print(f"  Workflow: {trigger.workflow}  ({wf_note})")
    print(f"  Config  : {trigger.config}")
    print(f"  Params  : {trigger.params}")
    if wf_ok:
        print("VALID")
        return 0
    print("INVALID — referenced workflow does not exist.", file=sys.stderr)
    return 1


def cmd_triggers_delete(name: str, yes: bool = False) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    triggers_dir = config.triggers_dir
    found: Path | None = None
    for ext in (".yaml", ".yml"):
        p = triggers_dir / f"{name}{ext}"
        if p.exists():
            found = p
            break

    if found is None:
        print(f"No trigger file found for '{name}' in {triggers_dir}.", file=sys.stderr)
        return 1

    if not yes:
        try:
            answer = input(f"Delete trigger file {found}? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            print("Aborted.")
            return 0

    found.unlink()
    print(f"Deleted: {found}")
    print("Note: restart the worker for this change to take effect (`solus worker stop && solus worker start`).")
    return 0


def cmd_triggers_examples() -> int:
    for ex in TRIGGER_EXAMPLES:
        print(f"\n# --- {ex['title']} ---")
        print(f"# {ex['description']}")
        print(ex["yaml"].rstrip())
    print()
    return 0

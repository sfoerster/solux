from __future__ import annotations

import json
import sys

from ..config import ConfigError, effective_external_modules_dir, load_config
from ..workflows.examples import WORKFLOW_EXAMPLES
from ..workflows.loader import WorkflowLoadError, list_workflows, load_workflow, workflow_to_dict
from ..workflows.registry import build_registry
from ..workflows.validation import validate_workflow
from .run import _print_dry_run


def cmd_workflows_list() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    workflows, invalid = list_workflows(workflow_dir=config.workflows_dir)
    for workflow in workflows:
        print(f"- {workflow.name}: {workflow.description}")
    if invalid:
        print("\nInvalid workflow definitions:")
        for err in invalid:
            print(f"  - {err}")
    return 0


def cmd_workflows_show(name: str) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    try:
        workflow = load_workflow(name, workflow_dir=config.workflows_dir)
    except WorkflowLoadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(workflow_to_dict(workflow), indent=2, ensure_ascii=False))
    return 0


def cmd_workflows_validate(name: str) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    try:
        workflow = load_workflow(name, workflow_dir=config.workflows_dir)
    except WorkflowLoadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    security_mode = str(getattr(getattr(config, "security", None), "mode", "trusted")).lower()
    registry = build_registry(external_dir=effective_external_modules_dir(config))
    result = validate_workflow(workflow, registry=registry, security_mode=security_mode)
    _print_dry_run(workflow, result, registry=registry)
    return 0 if result.valid else 1


def cmd_workflows_delete(name: str, yes: bool = False) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    workflows_dir = config.workflows_dir
    found = None
    for ext in (".yaml", ".yml"):
        p = workflows_dir / f"{name}{ext}"
        if p.exists():
            found = p
            break

    if found is None:
        print(f"No workflow file found for '{name}' in {workflows_dir}.", file=sys.stderr)
        print("Note: built-in workflows cannot be deleted.", file=sys.stderr)
        return 1

    if not yes:
        try:
            answer = input(f"Delete workflow file {found}? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            print("Aborted.")
            return 0

    found.unlink()
    print(f"Deleted: {found}")
    return 0


def cmd_workflows_examples() -> int:
    for ex in WORKFLOW_EXAMPLES:
        print(f"\n# --- {ex['title']} ---")
        print(f"# {ex['description']}")
        print(ex["yaml"].rstrip())
    print()
    return 0

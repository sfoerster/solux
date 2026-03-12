from __future__ import annotations

import yaml

from solus.workflows.examples import TRIGGER_EXAMPLES, WORKFLOW_EXAMPLES


def _workflow_examples_by_name() -> dict[str, dict]:
    workflows: dict[str, dict] = {}
    for example in WORKFLOW_EXAMPLES:
        payload = yaml.safe_load(example["yaml"])
        assert isinstance(payload, dict)
        name = str(payload.get("name", "")).strip()
        assert name
        workflows[name] = payload
    return workflows


def test_trigger_templates_reference_existing_workflow_templates() -> None:
    workflows = _workflow_examples_by_name()
    for example in TRIGGER_EXAMPLES:
        payload = yaml.safe_load(example["yaml"])
        assert isinstance(payload, dict)
        workflow_name = str(payload.get("workflow", "")).strip()
        assert workflow_name in workflows


def test_cron_and_email_templates_use_source_agnostic_workflows() -> None:
    workflows = _workflow_examples_by_name()
    source_sensitive_first_steps = {"input.source_fetch", "input.webpage_fetch"}

    for example in TRIGGER_EXAMPLES:
        payload = yaml.safe_load(example["yaml"])
        assert isinstance(payload, dict)
        trigger_type = str(payload.get("type", "")).strip()
        if trigger_type not in {"cron", "email_poll"}:
            continue

        workflow_name = str(payload.get("workflow", "")).strip()
        workflow = workflows[workflow_name]
        steps = workflow.get("steps", [])
        assert isinstance(steps, list) and steps

        first_step = steps[0]
        assert isinstance(first_step, dict)
        first_type = str(first_step.get("type", "")).strip()
        assert first_type not in source_sensitive_first_steps, (
            f"Trigger template {payload.get('name')!r} points at workflow {workflow_name!r} "
            f"whose first step {first_type!r} requires a URL/file source and is incompatible "
            "with cron/email trigger source semantics."
        )

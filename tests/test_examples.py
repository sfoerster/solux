from __future__ import annotations

import ast as _ast
import importlib.util
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from solux.triggers.loader import load_triggers
from solux.workflows.expr import _check_safe, evaluate_when
from solux.workflows.loader import list_workflows, load_workflow
from solux.workflows.registry import build_registry
from solux.workflows.validation import validate_workflow

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "docs" / "examples"
WORKFLOWS_DIR = EXAMPLES_DIR / "workflows"
TRIGGERS_DIR = EXAMPLES_DIR / "triggers"
MODULES_DIR = EXAMPLES_DIR / "modules"
ENV_EXAMPLE = EXAMPLES_DIR / ".env.example"
EXAMPLES_README = EXAMPLES_DIR / "README.md"


def _example_workflow_names() -> set[str]:
    names: set[str] = set()
    for workflow_file in sorted(WORKFLOWS_DIR.glob("*.yaml")) + sorted(WORKFLOWS_DIR.glob("*.yml")):
        payload = yaml.safe_load(workflow_file.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), f"{workflow_file} must be a YAML mapping"
        name = payload.get("name")
        assert isinstance(name, str) and name.strip(), f"{workflow_file} must define non-empty 'name'"
        names.add(name.strip())
    return names


def test_examples_workflows_load_and_validate() -> None:
    workflows, invalid = list_workflows(workflow_dir=WORKFLOWS_DIR)
    assert invalid == []

    expected_names = _example_workflow_names()
    available = {wf.name for wf in workflows}
    assert expected_names.issubset(available)

    registry = build_registry(external_dir=MODULES_DIR)
    for workflow_name in sorted(expected_names):
        wf = load_workflow(workflow_name, workflow_dir=WORKFLOWS_DIR)
        result = validate_workflow(wf, registry=registry, security_mode="trusted")
        errors = [issue for issue in result.issues if issue.level == "error"]
        assert errors == [], f"{workflow_name} has validation errors: {errors}"
        assert result.valid is True


def test_examples_triggers_load_and_reference_existing_workflows() -> None:
    triggers, errors = load_triggers(TRIGGERS_DIR)
    assert errors == []

    workflow_names = _example_workflow_names()
    for trigger in triggers:
        assert trigger.workflow in workflow_names


def test_example_embed_and_store_callback_is_optional() -> None:
    workflow = load_workflow("embed_and_store", workflow_dir=WORKFLOWS_DIR)
    callback_steps = [step for step in workflow.steps if step.name == "callback_to_node_a"]
    assert len(callback_steps) == 1
    callback_step = callback_steps[0]
    assert callback_step.type == "output.webhook"
    assert callback_step.when == "node_a_callback_url != ''"


def test_example_env_template_covers_interpolated_vars() -> None:
    used_keys: set[str] = set()
    pattern = re.compile(r"\$\{env:([^}]+)\}")
    for path in (
        sorted(WORKFLOWS_DIR.glob("*.yaml"))
        + sorted(WORKFLOWS_DIR.glob("*.yml"))
        + sorted(TRIGGERS_DIR.glob("*.yaml"))
        + sorted(TRIGGERS_DIR.glob("*.yml"))
    ):
        used_keys.update(pattern.findall(path.read_text(encoding="utf-8")))

    exported = set(
        re.findall(
            r"^export\s+([A-Z0-9_]+)=",
            ENV_EXAMPLE.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )
    assert used_keys - exported == set()


def test_examples_readme_referenced_paths_exist() -> None:
    readme = EXAMPLES_README.read_text(encoding="utf-8")
    paths = set(re.findall(r"`(docs/examples/[^`]+)`", readme))
    missing = [path for path in sorted(paths) if not (ROOT / path).exists()]
    assert missing == []


def test_example_subworkflow_references_are_satisfied() -> None:
    """Every 'type: workflow' step must name a workflow that exists in examples/workflows/.

    validate_workflow() only checks that 'workflow' is a known step type; it does
    not resolve the config.name reference.  A renamed or deleted sub-workflow would
    pass validation but fail at runtime.
    """
    example_names = _example_workflow_names()
    for yaml_path in sorted(WORKFLOWS_DIR.glob("*.yaml")):
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        for step in payload.get("steps", []):
            if step.get("type") == "workflow":
                sub_name = step.get("config", {}).get("name", "")
                assert sub_name in example_names, (
                    f"{yaml_path.name}: step '{step.get('name')}' calls sub-workflow "
                    f"'{sub_name}' which is not present in docs/examples/workflows/"
                )


def test_example_when_expressions_are_valid() -> None:
    """All when: expressions in example workflows must parse as safe AST.

    evaluate_when() is fail-open: a SyntaxError or unsafe node silently runs the
    step anyway and logs a warning.  Catching bad expressions here prevents
    conditional steps from always executing due to a silent parse failure.
    """
    for yaml_path in sorted(WORKFLOWS_DIR.glob("*.yaml")):
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        for step in payload.get("steps", []):
            expr = step.get("when")
            if expr is None:
                continue
            step_name = step.get("name", "<unnamed>")
            try:
                tree = _ast.parse(str(expr).strip(), mode="eval")
                _check_safe(tree)
            except (SyntaxError, ValueError) as exc:
                raise AssertionError(
                    f"{yaml_path.name}: step '{step_name}' has invalid when: expression {expr!r}: {exc}"
                ) from exc


def test_example_ingest_done_reads_result_param() -> None:
    """ingest_done.yaml must use params_loader with param_key='result'.

    Mirrors test_example_embed_and_store_callback_is_optional: both workflows
    rely on params_loader to bridge ctx.params into ctx.data, but they read
    different keys ('text' on Node B, 'result' on the Node A callback receiver).
    """
    workflow = load_workflow("ingest_done", workflow_dir=WORKFLOWS_DIR)
    loader_steps = [s for s in workflow.steps if s.type == "transform.params_loader"]
    assert len(loader_steps) == 1, "ingest_done must have exactly one transform.params_loader step"
    step = loader_steps[0]
    assert step.config.get("param_key") == "result", (
        f"ingest_done params_loader should read param_key='result', got {step.config.get('param_key')!r}"
    )
    assert step.config.get("output_key") == "summary_text", (
        f"ingest_done params_loader should write output_key='summary_text', got {step.config.get('output_key')!r}"
    )


def test_example_custom_modules_import_cleanly() -> None:
    """Every .py file in examples/modules/ must import without error and expose MODULE + handle.

    test_examples_workflows_load_and_validate catches missing modules as an
    'unknown step type' error, but the message doesn't identify the broken file.
    This test fails fast with a clear pointer to the offending module.
    """
    for module_path in sorted(MODULES_DIR.glob("*.py")):
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        assert spec is not None and spec.loader is not None, f"Could not create importlib spec for {module_path.name}"
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as exc:
            raise AssertionError(f"{module_path.name} raised an error on import: {exc}") from exc
        assert hasattr(mod, "MODULE"), f"{module_path.name} must define MODULE = ModuleSpec(...)"
        assert hasattr(mod, "handle"), f"{module_path.name} must define handle(ctx, step) -> ctx"
        assert callable(mod.handle), f"{module_path.name}: handle must be callable"


def test_params_loader_callback_guard_behavior() -> None:
    """params_loader must write node_a_callback_url into ctx.data so the when: guard works.

    The embed_and_store callback step uses:
        when: node_a_callback_url != ''

    params_loader writes ctx.data["node_a_callback_url"] from NODE_A_CALLBACK_URL.
    This test verifies the full chain: env var → ctx.data → evaluate_when result.
    """
    spec = importlib.util.spec_from_file_location("params_loader_guard_test", MODULES_DIR / "params_loader.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    step = MagicMock()
    step.config = {"param_key": "text", "output_key": "cleaned_text"}

    # When the env var is set the callback step should execute.
    with patch.dict(os.environ, {"NODE_A_CALLBACK_URL": "http://node-a.local:8765/api/trigger/ingest_done"}):
        ctx = MagicMock()
        ctx.params = {"text": "forwarded document text"}
        ctx.data = {}
        mod.handle(ctx, step)
        assert ctx.data["node_a_callback_url"] == "http://node-a.local:8765/api/trigger/ingest_done"
        assert evaluate_when("node_a_callback_url != ''", ctx.data) is True

    # When the env var is empty the callback step should be skipped.
    with patch.dict(os.environ, {"NODE_A_CALLBACK_URL": ""}):
        ctx = MagicMock()
        ctx.params = {"text": "forwarded document text"}
        ctx.data = {}
        mod.handle(ctx, step)
        assert ctx.data["node_a_callback_url"] == ""
        assert evaluate_when("node_a_callback_url != ''", ctx.data) is False

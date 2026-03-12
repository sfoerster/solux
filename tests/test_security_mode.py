from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from solus.modules.spec import ModuleSpec
from solus.workflows.engine import execute_workflow
from solus.workflows.models import Context, Step, Workflow
from solus.workflows.registry import StepRegistry


def _passthrough(ctx: Context, step: Step) -> Context:
    del step
    ctx.data["ran"] = True
    return ctx


def _ctx(mode: str) -> Context:
    return Context(
        source="example",
        source_id="abc123",
        data={"workflow_name": "wf", "runtime": {}},
        config=SimpleNamespace(security=SimpleNamespace(mode=mode)),
        logger=logging.getLogger("test.security"),
        params={},
    )


def test_untrusted_mode_blocks_trusted_only_module() -> None:
    registry = StepRegistry()
    spec = ModuleSpec(
        name="danger",
        version="0.1.0",
        category="output",
        description="dangerous sink",
        handler=_passthrough,
        safety="trusted_only",
    )
    registry.register(spec.step_type, spec.handler, spec=spec)
    workflow = Workflow(
        name="wf",
        description="",
        steps=[Step(name="danger_step", type=spec.step_type, config={})],
    )

    with pytest.raises(RuntimeError, match="trusted-only module|failed validation"):
        execute_workflow(workflow, _ctx("untrusted"), registry=registry)


def test_untrusted_mode_allows_safe_module() -> None:
    registry = StepRegistry()
    spec = ModuleSpec(
        name="safe_mod",
        version="0.1.0",
        category="transform",
        description="safe transform",
        handler=_passthrough,
        safety="safe",
    )
    registry.register(spec.step_type, spec.handler, spec=spec)
    workflow = Workflow(
        name="wf",
        description="",
        steps=[Step(name="safe_step", type=spec.step_type, config={})],
    )

    out = execute_workflow(workflow, _ctx("untrusted"), registry=registry)
    assert out.data["ran"] is True


def test_untrusted_mode_blocks_network_module() -> None:
    registry = StepRegistry()
    spec = ModuleSpec(
        name="network_mod",
        version="0.1.0",
        category="input",
        description="safe but networked",
        handler=_passthrough,
        safety="safe",
        network=True,
    )
    registry.register(spec.step_type, spec.handler, spec=spec)
    workflow = Workflow(
        name="wf",
        description="",
        steps=[Step(name="network_step", type=spec.step_type, config={})],
    )

    with pytest.raises(RuntimeError, match="network-enabled module|failed validation"):
        execute_workflow(workflow, _ctx("untrusted"), registry=registry)


def test_when_error_skips_trusted_only_step() -> None:
    """Broken when: on a trusted_only step → step skipped (fail-closed)."""
    registry = StepRegistry()
    spec = ModuleSpec(
        name="danger",
        version="0.1.0",
        category="output",
        description="dangerous sink",
        handler=_passthrough,
        safety="trusted_only",
    )
    registry.register(spec.step_type, spec.handler, spec=spec)
    workflow = Workflow(
        name="wf",
        description="",
        steps=[Step(name="danger_step", type=spec.step_type, config={}, when="broken !!! expr")],
    )
    # In untrusted mode, trusted_only steps are blocked entirely by _enforce_step_safety.
    # Use trusted mode so the when: evaluation path is exercised.
    ctx = _ctx("trusted")
    out = execute_workflow(workflow, ctx, registry=registry)
    # Step should be skipped (fail-closed), so "ran" should not be set
    assert "ran" not in out.data


def test_when_error_runs_safe_step() -> None:
    """Broken when: on a safe step → step runs (existing fail-open)."""
    registry = StepRegistry()
    spec = ModuleSpec(
        name="safe_mod",
        version="0.1.0",
        category="transform",
        description="safe transform",
        handler=_passthrough,
        safety="safe",
    )
    registry.register(spec.step_type, spec.handler, spec=spec)
    workflow = Workflow(
        name="wf",
        description="",
        steps=[Step(name="safe_step", type=spec.step_type, config={}, when="broken !!! expr")],
    )
    ctx = _ctx("trusted")
    out = execute_workflow(workflow, ctx, registry=registry)
    # Step should run (fail-open)
    assert out.data["ran"] is True


def test_untrusted_mode_blocks_unspec_handler() -> None:
    """Handler without a spec is blocked in untrusted mode."""
    registry = StepRegistry()
    registry.register("test.unspec", _passthrough)  # no spec
    workflow = Workflow(
        name="wf",
        description="",
        steps=[Step(name="unspec_step", type="test.unspec", config={})],
    )
    with pytest.raises(RuntimeError, match="no module spec"):
        execute_workflow(workflow, _ctx("untrusted"), registry=registry)


def test_trusted_mode_allows_unspec_handler() -> None:
    """Handler without a spec is allowed in trusted mode."""
    registry = StepRegistry()
    registry.register("test.unspec", _passthrough)  # no spec
    workflow = Workflow(
        name="wf",
        description="",
        steps=[Step(name="unspec_step", type="test.unspec", config={})],
    )
    out = execute_workflow(workflow, _ctx("trusted"), registry=registry)
    assert out.data["ran"] is True


def test_trusted_mode_allows_trusted_only_module() -> None:
    registry = StepRegistry()
    spec = ModuleSpec(
        name="db_sink",
        version="0.1.0",
        category="output",
        description="trusted sink",
        handler=_passthrough,
        safety="trusted_only",
    )
    registry.register(spec.step_type, spec.handler, spec=spec)
    workflow = Workflow(
        name="wf",
        description="",
        steps=[Step(name="sink_step", type=spec.step_type, config={})],
    )

    out = execute_workflow(workflow, _ctx("trusted"), registry=registry)
    assert out.data["ran"] is True

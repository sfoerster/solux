"""Tests for workflow engine security enforcement: fail-closed when:,
untrusted mode, on_error recovery, timeout+trusted_only, foreach edge cases,
and post-step schema validation."""

from __future__ import annotations

import logging
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from solus.workflows.engine import (
    StepTimeoutError,
    _evaluate_when_for_step,
    _enforce_step_safety,
    execute_workflow,
)
from solus.workflows.models import Context, ContextKeys, Step, Workflow
from solus.workflows.registry import StepRegistry
from solus.modules.spec import ModuleSpec, ContextKey


def _make_config(mode: str = "trusted") -> MagicMock:
    config = MagicMock()
    config.security.mode = mode
    config.security.strict_env_vars = False
    config.workflows_dir = None
    config.ollama.base_url = "http://localhost:11434"
    config.ollama.model = "test"
    return config


def _ctx(data: dict | None = None, mode: str = "trusted") -> Context:
    return Context(
        source="test",
        source_id="test001",
        data=dict(data or {}),
        config=_make_config(mode),
        logger=logging.getLogger("test"),
    )


def _identity_handler(ctx: Context, step: Step) -> Context:
    return ctx


def _writing_handler(ctx: Context, step: Step) -> Context:
    ctx.data["output_text"] = "result"
    return ctx


def _failing_handler(ctx: Context, step: Step) -> Context:
    raise RuntimeError("step failed on purpose")


# ---------------------------------------------------------------------------
# _evaluate_when_for_step: fail-closed for trusted_only modules
# ---------------------------------------------------------------------------


class TestEvaluateWhenForStep:
    def test_safe_step_fail_open(self) -> None:
        """Normal steps fail-open on expression errors."""
        reg = StepRegistry()
        spec = ModuleSpec(
            name="safe_mod", version="0.1", category="transform",
            description="", handler=_identity_handler,
        )
        reg.register("transform.safe_mod", _identity_handler, spec=spec)
        # Bad expression → fail-open → True
        assert _evaluate_when_for_step("???broken", {}, "transform.safe_mod", reg) is True

    def test_trusted_only_fail_closed(self) -> None:
        """trusted_only steps fail-closed on expression errors."""
        reg = StepRegistry()
        spec = ModuleSpec(
            name="webhook", version="0.1", category="output",
            description="", handler=_identity_handler, safety="trusted_only",
        )
        reg.register("output.webhook", _identity_handler, spec=spec)
        # Bad expression → fail-closed → False (skip step)
        assert _evaluate_when_for_step("???broken", {}, "output.webhook", reg) is False

    def test_trusted_only_normal_eval(self) -> None:
        """trusted_only steps evaluate normally when expression is valid."""
        reg = StepRegistry()
        spec = ModuleSpec(
            name="webhook", version="0.1", category="output",
            description="", handler=_identity_handler, safety="trusted_only",
        )
        reg.register("output.webhook", _identity_handler, spec=spec)
        assert _evaluate_when_for_step("x == 1", {"x": 1}, "output.webhook", reg) is True
        assert _evaluate_when_for_step("x == 1", {"x": 2}, "output.webhook", reg) is False

    def test_unknown_step_uses_fail_open(self) -> None:
        """Steps not in registry use the default fail-open evaluator."""
        reg = StepRegistry()
        assert _evaluate_when_for_step("True", {}, "unknown.step", reg) is True


# ---------------------------------------------------------------------------
# _enforce_step_safety: untrusted mode enforcement
# ---------------------------------------------------------------------------


class TestEnforceStepSafety:
    def test_trusted_mode_allows_trusted_only(self) -> None:
        ctx = _ctx(mode="trusted")
        reg = StepRegistry()
        spec = ModuleSpec(
            name="webhook", version="0.1", category="output",
            description="", handler=_identity_handler, safety="trusted_only",
        )
        reg.register("output.webhook", _identity_handler, spec=spec)
        # Should not raise
        _enforce_step_safety(ctx, "output.webhook", "send", reg)

    def test_untrusted_rejects_trusted_only(self) -> None:
        ctx = _ctx(mode="untrusted")
        reg = StepRegistry()
        spec = ModuleSpec(
            name="webhook", version="0.1", category="output",
            description="", handler=_identity_handler, safety="trusted_only",
        )
        reg.register("output.webhook", _identity_handler, spec=spec)
        with pytest.raises(RuntimeError, match="trusted-only module"):
            _enforce_step_safety(ctx, "output.webhook", "send", reg)

    def test_untrusted_rejects_network_module(self) -> None:
        ctx = _ctx(mode="untrusted")
        reg = StepRegistry()
        spec = ModuleSpec(
            name="fetch", version="0.1", category="input",
            description="", handler=_identity_handler, network=True,
        )
        reg.register("input.fetch", _identity_handler, spec=spec)
        with pytest.raises(RuntimeError, match="network-enabled module"):
            _enforce_step_safety(ctx, "input.fetch", "fetch_page", reg)

    def test_untrusted_rejects_unknown_spec(self) -> None:
        ctx = _ctx(mode="untrusted")
        reg = StepRegistry()
        with pytest.raises(RuntimeError, match="has no module spec"):
            _enforce_step_safety(ctx, "custom.thing", "my_step", reg)

    def test_trusted_allows_unknown_spec(self) -> None:
        ctx = _ctx(mode="trusted")
        reg = StepRegistry()
        # Should not raise — trusted mode is permissive
        _enforce_step_safety(ctx, "custom.thing", "my_step", reg)


# ---------------------------------------------------------------------------
# Timeout + trusted_only / network validation
# ---------------------------------------------------------------------------


class TestTimeoutSafetyValidation:
    def test_timeout_rejected_for_trusted_only(self) -> None:
        """Validation catches timeout on trusted_only modules before execution."""
        reg = StepRegistry()
        spec = ModuleSpec(
            name="webhook", version="0.1", category="output",
            description="", handler=_identity_handler, safety="trusted_only",
        )
        reg.register("output.webhook", _identity_handler, spec=spec)
        workflow = Workflow(
            name="test_wf", description="",
            steps=[Step(name="send", type="output.webhook", config={}, timeout_seconds=30)],
        )
        ctx = _ctx()
        with pytest.raises(RuntimeError, match="failed validation"):
            execute_workflow(workflow, ctx, registry=reg)

    def test_timeout_rejected_for_network_module(self) -> None:
        """Validation catches timeout on network modules before execution."""
        reg = StepRegistry()
        spec = ModuleSpec(
            name="fetch", version="0.1", category="input",
            description="", handler=_identity_handler, network=True,
        )
        reg.register("input.fetch", _identity_handler, spec=spec)
        workflow = Workflow(
            name="test_wf", description="",
            steps=[Step(name="get", type="input.fetch", config={}, timeout_seconds=10)],
        )
        ctx = _ctx()
        with pytest.raises(RuntimeError, match="failed validation"):
            execute_workflow(workflow, ctx, registry=reg)


# ---------------------------------------------------------------------------
# Foreach edge cases
# ---------------------------------------------------------------------------


class TestForeachEdgeCases:
    def test_foreach_non_list_coerced_to_empty(self) -> None:
        """Non-list foreach values should be coerced to empty list."""
        reg = StepRegistry()
        reg.register("transform.noop", _identity_handler)
        workflow = Workflow(
            name="test_wf", description="",
            steps=[Step(name="iter", type="transform.noop", config={}, foreach="items")],
        )
        ctx = _ctx(data={"items": "not-a-list"})
        result = execute_workflow(workflow, ctx, registry=reg)
        assert result is not None  # Should not crash

    def test_foreach_missing_key_is_empty(self) -> None:
        """Missing foreach key should default to empty list."""
        reg = StepRegistry()
        reg.register("transform.noop", _identity_handler)
        workflow = Workflow(
            name="test_wf", description="",
            steps=[Step(name="iter", type="transform.noop", config={}, foreach="nonexistent")],
        )
        ctx = _ctx()
        result = execute_workflow(workflow, ctx, registry=reg)
        assert result is not None


# ---------------------------------------------------------------------------
# Post-step schema validation warnings
# ---------------------------------------------------------------------------


class TestPostStepSchemaWarning:
    def test_warning_on_missing_write_key(self, caplog) -> None:
        """Engine should warn when a module's declared writes are missing after execution."""
        reg = StepRegistry()
        spec = ModuleSpec(
            name="noop", version="0.1", category="transform",
            description="", handler=_identity_handler,
            writes=(ContextKey("output_text", "Expected output"),),
        )
        reg.register("transform.noop", _identity_handler, spec=spec)
        workflow = Workflow(
            name="test_wf", description="",
            steps=[Step(name="do_nothing", type="transform.noop", config={})],
        )
        ctx = _ctx()
        with caplog.at_level(logging.WARNING):
            execute_workflow(workflow, ctx, registry=reg)
        assert any("expected write key 'output_text' not found" in r.message for r in caplog.records)

    def test_no_warning_when_write_key_present(self, caplog) -> None:
        reg = StepRegistry()
        spec = ModuleSpec(
            name="writer", version="0.1", category="transform",
            description="", handler=_writing_handler,
            writes=(ContextKey("output_text", "Output"),),
        )
        reg.register("transform.writer", _writing_handler, spec=spec)
        workflow = Workflow(
            name="test_wf", description="",
            steps=[Step(name="write", type="transform.writer", config={})],
        )
        ctx = _ctx()
        with caplog.at_level(logging.WARNING):
            execute_workflow(workflow, ctx, registry=reg)
        assert not any("expected write key" in r.message for r in caplog.records)

    def test_no_warning_for_underscore_keys(self, caplog) -> None:
        """Internal keys starting with _ should not trigger warnings."""
        reg = StepRegistry()
        spec = ModuleSpec(
            name="noop", version="0.1", category="transform",
            description="", handler=_identity_handler,
            writes=(ContextKey("_internal", "Internal key"),),
        )
        reg.register("transform.noop", _identity_handler, spec=spec)
        workflow = Workflow(
            name="test_wf", description="",
            steps=[Step(name="step", type="transform.noop", config={})],
        )
        ctx = _ctx()
        with caplog.at_level(logging.WARNING):
            execute_workflow(workflow, ctx, registry=reg)
        assert not any("expected write key" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# on_error workflow load failure
# ---------------------------------------------------------------------------


class TestOnErrorLoadFailure:
    def test_on_error_workflow_not_found_raises_original(self) -> None:
        """If on_error workflow can't be loaded, the original exception propagates."""
        reg = StepRegistry()
        reg.register("transform.fail", _failing_handler)
        workflow = Workflow(
            name="test_wf", description="",
            steps=[Step(name="bad", type="transform.fail", config={}, on_error="nonexistent_wf")],
        )
        ctx = _ctx()
        # Should raise the original RuntimeError, not a WorkflowLoadError
        with pytest.raises(RuntimeError, match="step failed on purpose"):
            execute_workflow(workflow, ctx, registry=reg)

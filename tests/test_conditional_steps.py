"""Tests for conditional (when:) steps, foreach: iteration, sub-workflow, branch, on_error, and parallel foreach."""

from __future__ import annotations

import logging
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from unittest.mock import patch

from solux.workflows.expr import evaluate_when
from solux.workflows.models import Context, ContextKeys, Step, Workflow
from solux.workflows.registry import StepRegistry


def _make_config() -> MagicMock:
    config = MagicMock()
    config.ollama.base_url = "http://localhost:11434"
    config.ollama.model = "llama3.1:8b"
    return config


def _ctx(data: dict | None = None) -> Context:
    return Context(
        source="test",
        source_id="test001",
        data=dict(data or {}),
        config=_make_config(),
        logger=logging.getLogger("test"),
    )


def _registry_with_handler(step_type: str, handler) -> StepRegistry:
    reg = StepRegistry()
    reg.register(step_type, handler)
    return reg


# ---------------------------------------------------------------------------
# evaluate_when
# ---------------------------------------------------------------------------


def test_when_true_literal() -> None:
    assert evaluate_when("True", {}) is True


def test_when_false_literal() -> None:
    assert evaluate_when("False", {}) is False


def test_when_key_present_and_truthy() -> None:
    assert evaluate_when("result", {"result": "hello"}) is True


def test_when_key_present_and_falsy() -> None:
    assert evaluate_when("result", {"result": ""}) is False
    assert evaluate_when("result", {"result": None}) is False


def test_when_key_missing_is_falsy() -> None:
    assert evaluate_when("missing_key", {}) is False


def test_when_none_comparison() -> None:
    assert evaluate_when("result is not None", {"result": "value"}) is True
    assert evaluate_when("result is not None", {}) is False
    assert evaluate_when("result is None", {}) is True


def test_when_equality() -> None:
    assert evaluate_when("status == 'done'", {"status": "done"}) is True
    assert evaluate_when("status == 'done'", {"status": "pending"}) is False


def test_when_inequality() -> None:
    assert evaluate_when("count != 0", {"count": 5}) is True
    assert evaluate_when("count != 0", {"count": 0}) is False


def test_when_comparison_operators() -> None:
    assert evaluate_when("count > 5", {"count": 10}) is True
    assert evaluate_when("count > 5", {"count": 3}) is False
    assert evaluate_when("count >= 5", {"count": 5}) is True
    assert evaluate_when("count < 10", {"count": 5}) is True


def test_when_and_or() -> None:
    data = {"a": True, "b": False, "c": True}
    assert evaluate_when("a and c", data) is True
    assert evaluate_when("a and b", data) is False
    assert evaluate_when("a or b", data) is True
    assert evaluate_when("b or b", data) is False


def test_when_not() -> None:
    assert evaluate_when("not False", {}) is True
    assert evaluate_when("not result", {"result": ""}) is True
    assert evaluate_when("not result", {"result": "value"}) is False


def test_when_in_operator() -> None:
    assert evaluate_when("'apple' in fruits", {"fruits": ["apple", "banana"]}) is True
    assert evaluate_when("'mango' in fruits", {"fruits": ["apple", "banana"]}) is False


def test_when_parse_error_returns_true() -> None:
    # Fail-open: bad syntax → step still runs
    assert evaluate_when("this is not valid python !@#", {}) is True


def test_when_unsafe_expression_returns_true() -> None:
    # Unsafe node (function call) → step still runs
    assert evaluate_when("__import__('os').getcwd()", {}) is True


def test_when_attribute_access_rejected() -> None:
    # Attribute access is rejected (fail-open: returns True + warning logged)
    data = {"obj": MagicMock()}
    data["obj"].value = 42
    result = evaluate_when("obj.value", data)
    assert result is True  # fail-open


def test_when_dunder_attribute_rejected() -> None:
    # Dunder attribute access is also rejected
    data = {"config": MagicMock()}
    result = evaluate_when("config.__class__", data)
    assert result is True  # fail-open


# ---------------------------------------------------------------------------
# Engine: conditional step execution
# ---------------------------------------------------------------------------


def test_engine_skips_step_when_false() -> None:
    from solux.workflows.engine import execute_workflow

    calls = []

    def handler(ctx: Context, step: Step) -> Context:
        calls.append(step.name)
        return ctx

    reg = StepRegistry()
    reg.register("test.step", handler)

    wf = Workflow(
        name="cond_test",
        description="",
        steps=[
            Step(name="always", type="test.step", when=None),
            Step(name="skip_me", type="test.step", when="False"),
            Step(name="run_me", type="test.step", when="True"),
        ],
    )
    ctx = _ctx()
    result = execute_workflow(wf, ctx, registry=reg)

    assert "always" in calls
    assert "skip_me" not in calls
    assert "run_me" in calls


def test_engine_runs_step_when_key_present() -> None:
    from solux.workflows.engine import execute_workflow

    ran = []

    def setter(ctx: Context, step: Step) -> Context:
        ctx.data["flag"] = True
        return ctx

    def conditional(ctx: Context, step: Step) -> Context:
        ran.append("conditional")
        return ctx

    reg = StepRegistry()
    reg.register("test.setter", setter)
    reg.register("test.conditional", conditional)

    wf = Workflow(
        name="data_cond",
        description="",
        steps=[
            Step(name="set_flag", type="test.setter"),
            Step(name="cond_step", type="test.conditional", when="flag"),
        ],
    )
    ctx = _ctx()
    execute_workflow(wf, ctx, registry=reg)
    assert "conditional" in ran


def test_engine_skips_step_when_key_absent() -> None:
    from solux.workflows.engine import execute_workflow

    ran = []

    def conditional(ctx: Context, step: Step) -> Context:
        ran.append("conditional")
        return ctx

    reg = StepRegistry()
    reg.register("test.step", conditional)

    wf = Workflow(
        name="absent_key",
        description="",
        steps=[
            Step(name="cond_step", type="test.step", when="missing_key"),
        ],
    )
    ctx = _ctx()
    execute_workflow(wf, ctx, registry=reg)
    assert ran == []


# ---------------------------------------------------------------------------
# Engine: foreach iteration
# ---------------------------------------------------------------------------


def test_engine_foreach_iterates_items() -> None:
    from solux.workflows.engine import execute_workflow

    seen_items = []

    def collect(ctx: Context, step: Step) -> Context:
        seen_items.append(ctx.data.get("_item"))
        return ctx

    reg = StepRegistry()
    reg.register("test.collect", collect)

    wf = Workflow(
        name="foreach_test",
        description="",
        steps=[
            Step(name="each", type="test.collect", foreach="my_list"),
        ],
    )
    ctx = _ctx(data={"my_list": ["a", "b", "c"]})
    execute_workflow(wf, ctx, registry=reg)
    assert seen_items == ["a", "b", "c"]


def test_engine_foreach_provides_index() -> None:
    from solux.workflows.engine import execute_workflow

    seen_indices = []

    def collect(ctx: Context, step: Step) -> Context:
        seen_indices.append(ctx.data.get("_index"))
        return ctx

    reg = StepRegistry()
    reg.register("test.collect", collect)

    wf = Workflow(
        name="foreach_index",
        description="",
        steps=[
            Step(name="each", type="test.collect", foreach="items"),
        ],
    )
    ctx = _ctx(data={"items": ["x", "y", "z"]})
    execute_workflow(wf, ctx, registry=reg)
    assert seen_indices == [0, 1, 2]


def test_engine_foreach_empty_list_no_calls() -> None:
    from solux.workflows.engine import execute_workflow

    calls = []

    def handler(ctx: Context, step: Step) -> Context:
        calls.append(True)
        return ctx

    reg = StepRegistry()
    reg.register("test.handler", handler)

    wf = Workflow(
        name="foreach_empty",
        description="",
        steps=[
            Step(name="each", type="test.handler", foreach="items"),
        ],
    )
    ctx = _ctx(data={"items": []})
    execute_workflow(wf, ctx, registry=reg)
    assert calls == []


def test_engine_foreach_missing_key_no_calls() -> None:
    from solux.workflows.engine import execute_workflow

    calls = []

    def handler(ctx: Context, step: Step) -> Context:
        calls.append(True)
        return ctx

    reg = StepRegistry()
    reg.register("test.handler", handler)

    wf = Workflow(
        name="foreach_missing",
        description="",
        steps=[
            Step(name="each", type="test.handler", foreach="no_such_key"),
        ],
    )
    ctx = _ctx()
    execute_workflow(wf, ctx, registry=reg)
    assert calls == []


def test_engine_foreach_accumulates_side_effects() -> None:
    from solux.workflows.engine import execute_workflow

    def append_result(ctx: Context, step: Step) -> Context:
        results = list(ctx.data.get("results", []))
        results.append(f"processed:{ctx.data.get('_item')}")
        ctx.data["results"] = results
        return ctx

    reg = StepRegistry()
    reg.register("test.append", append_result)

    wf = Workflow(
        name="foreach_accumulate",
        description="",
        steps=[
            Step(name="each", type="test.append", foreach="words"),
        ],
    )
    ctx = _ctx(data={"words": ["foo", "bar"]})
    result = execute_workflow(wf, ctx, registry=reg)
    assert result.data["results"] == ["processed:foo", "processed:bar"]


# ---------------------------------------------------------------------------
# Sub-workflow steps (meta/subworkflow)
# ---------------------------------------------------------------------------


def test_subworkflow_step_runs_child_workflow() -> None:
    from solux.modules.meta.subworkflow import handle

    inner_ran = []

    def inner_handler(ctx: Context, step: Step) -> Context:
        inner_ran.append("ran")
        ctx.data["inner_result"] = "done"
        return ctx

    child_wf = Workflow(
        name="child",
        description="child workflow",
        steps=[Step(name="inner", type="test.inner")],
    )

    child_reg = StepRegistry()
    child_reg.register("test.inner", inner_handler)

    ctx = _ctx()
    step = Step(name="run_child", type="workflow", config={"name": "child"})

    # load_workflow is imported inside handle(), so patch at the loader module level
    with patch("solux.workflows.loader.load_workflow", return_value=child_wf):
        with patch("solux.workflows.engine.global_registry", child_reg):
            result = handle(ctx, step)

    assert inner_ran == ["ran"]
    assert result.data.get("inner_result") == "done"


def test_subworkflow_step_missing_name_raises() -> None:
    from solux.modules.meta.subworkflow import handle

    ctx = _ctx()
    step = Step(name="run_child", type="workflow", config={})
    with pytest.raises(RuntimeError, match="'name' config"):
        handle(ctx, step)


def test_subworkflow_cycle_detection_raises() -> None:
    """A circular reference A -> A must raise RuntimeError, not recurse infinitely."""
    from solux.modules.meta.subworkflow import handle

    # Simulate being mid-way through executing workflow "parent"
    ctx = _ctx(data={"_subworkflow_stack": ["parent"]})
    # Now try to invoke "parent" again as a sub-workflow
    step = Step(name="recurse", type="workflow", config={"name": "parent"})
    with pytest.raises(RuntimeError, match="circular"):
        handle(ctx, step)


def test_subworkflow_indirect_cycle_detection_raises() -> None:
    """An indirect cycle A -> B -> A must also be caught."""
    from solux.modules.meta.subworkflow import handle

    ctx = _ctx(data={"_subworkflow_stack": ["a", "b"]})
    step = Step(name="recurse", type="workflow", config={"name": "a"})
    with pytest.raises(RuntimeError, match="circular"):
        handle(ctx, step)


def test_engine_foreach_cap_raises() -> None:
    """Workflows iterating more than _FOREACH_MAX_ITEMS items must be rejected."""
    from solux.workflows.engine import _FOREACH_MAX_ITEMS, execute_workflow

    calls = []

    def collector(ctx: Context, step: Step) -> Context:
        calls.append(step)
        return ctx

    reg = StepRegistry()
    reg.register("test.collect", collector)

    # Build a list that exceeds the cap
    oversized = list(range(_FOREACH_MAX_ITEMS + 1))

    wf = Workflow(
        name="cap_test",
        description="",
        steps=[Step(name="each", type="test.collect", foreach="big_list")],
    )

    ctx = _ctx(data={"big_list": oversized})
    with pytest.raises(RuntimeError, match="exceeds the maximum"):
        execute_workflow(wf, ctx, registry=reg)
    # Nothing should have been processed
    assert calls == []


# ---------------------------------------------------------------------------
# Branch meta module
# ---------------------------------------------------------------------------


def test_branch_selects_correct_workflow() -> None:
    from solux.modules.meta.branch import handle

    inner_ran = []

    def inner_handler(ctx: Context, step: Step) -> Context:
        inner_ran.append(step.name)
        ctx.data["routed"] = "invoice"
        return ctx

    invoice_wf = Workflow(
        name="process_invoice",
        description="",
        steps=[Step(name="invoice_step", type="test.inner")],
    )

    child_reg = StepRegistry()
    child_reg.register("test.inner", inner_handler)

    ctx = _ctx(data={"doc_type": "invoice"})
    step = Step(
        name="route",
        type="branch",
        config={
            "condition_key": "doc_type",
            "branches": {"report": "process_report", "invoice": "process_invoice"},
        },
    )

    with patch("solux.workflows.loader.load_workflow", return_value=invoice_wf):
        with patch("solux.workflows.engine.global_registry", child_reg):
            result = handle(ctx, step)

    assert inner_ran == ["invoice_step"]
    assert result.data["routed"] == "invoice"


def test_branch_uses_default_when_no_match() -> None:
    from solux.modules.meta.branch import handle

    inner_ran = []

    def inner_handler(ctx: Context, step: Step) -> Context:
        inner_ran.append("default")
        return ctx

    default_wf = Workflow(
        name="process_generic",
        description="",
        steps=[Step(name="generic_step", type="test.inner")],
    )

    child_reg = StepRegistry()
    child_reg.register("test.inner", inner_handler)

    ctx = _ctx(data={"doc_type": "unknown_type"})
    step = Step(
        name="route",
        type="branch",
        config={
            "condition_key": "doc_type",
            "branches": {"report": "process_report"},
            "default": "process_generic",
        },
    )

    with patch("solux.workflows.loader.load_workflow", return_value=default_wf):
        with patch("solux.workflows.engine.global_registry", child_reg):
            result = handle(ctx, step)

    assert inner_ran == ["default"]


def test_branch_raises_without_default_on_no_match() -> None:
    from solux.modules.meta.branch import handle

    ctx = _ctx(data={"doc_type": "unknown"})
    step = Step(
        name="route",
        type="branch",
        config={
            "condition_key": "doc_type",
            "branches": {"report": "process_report"},
        },
    )
    with pytest.raises(RuntimeError, match="no branch matched"):
        handle(ctx, step)


def test_branch_missing_condition_key_raises() -> None:
    from solux.modules.meta.branch import handle

    ctx = _ctx()
    step = Step(name="route", type="branch", config={"branches": {"a": "wf_a"}})
    with pytest.raises(RuntimeError, match="condition_key"):
        handle(ctx, step)


def test_branch_cycle_detection() -> None:
    from solux.modules.meta.branch import handle

    ctx = _ctx(data={"doc_type": "a", "_subworkflow_stack": ["process_a"]})
    step = Step(
        name="route",
        type="branch",
        config={
            "condition_key": "doc_type",
            "branches": {"a": "process_a"},
        },
    )
    with pytest.raises(RuntimeError, match="circular"):
        handle(ctx, step)


# ---------------------------------------------------------------------------
# on_error handling
# ---------------------------------------------------------------------------


def test_on_error_runs_fallback_workflow() -> None:
    from solux.workflows.engine import execute_workflow

    calls = []

    def failing_handler(ctx: Context, step: Step) -> Context:
        raise RuntimeError("boom")

    def recovery_handler(ctx: Context, step: Step) -> Context:
        calls.append("recovered")
        ctx.data["recovered"] = True
        return ctx

    recovery_wf = Workflow(
        name="recovery",
        description="",
        steps=[Step(name="fix", type="test.recovery")],
    )

    reg = StepRegistry()
    reg.register("test.fail", failing_handler)
    reg.register("test.recovery", recovery_handler)

    wf = Workflow(
        name="on_error_test",
        description="",
        steps=[Step(name="risky", type="test.fail", on_error="recovery")],
    )

    ctx = _ctx()
    with patch("solux.workflows.loader.load_workflow", return_value=recovery_wf):
        result = execute_workflow(wf, ctx, registry=reg)

    assert calls == ["recovered"]
    assert result.data["recovered"] is True


def test_on_error_sets_error_context_keys() -> None:
    from solux.workflows.engine import execute_workflow

    def failing_handler(ctx: Context, step: Step) -> Context:
        raise ValueError("test error message")

    def noop(ctx: Context, step: Step) -> Context:
        return ctx

    recovery_wf = Workflow(
        name="recovery",
        description="",
        steps=[Step(name="noop", type="test.noop")],
    )

    reg = StepRegistry()
    reg.register("test.fail", failing_handler)
    reg.register("test.noop", noop)

    wf = Workflow(
        name="ctx_keys_test",
        description="",
        steps=[Step(name="bad_step", type="test.fail", on_error="recovery")],
    )

    ctx = _ctx()
    with patch("solux.workflows.loader.load_workflow", return_value=recovery_wf):
        result = execute_workflow(wf, ctx, registry=reg)

    assert result.data[ContextKeys.ERROR] == "test error message"
    assert result.data[ContextKeys.ERROR_STEP] == "bad_step"


def test_on_error_fallback_failure_raises_original() -> None:
    from solux.workflows.engine import execute_workflow

    def failing_handler(ctx: Context, step: Step) -> Context:
        raise RuntimeError("original error")

    def also_failing(ctx: Context, step: Step) -> Context:
        raise RuntimeError("recovery also failed")

    recovery_wf = Workflow(
        name="bad_recovery",
        description="",
        steps=[Step(name="also_fail", type="test.also_fail")],
    )

    reg = StepRegistry()
    reg.register("test.fail", failing_handler)
    reg.register("test.also_fail", also_failing)

    wf = Workflow(
        name="double_fail",
        description="",
        steps=[Step(name="risky", type="test.fail", on_error="bad_recovery")],
    )

    ctx = _ctx()
    with patch("solux.workflows.loader.load_workflow", return_value=recovery_wf):
        with pytest.raises(RuntimeError, match="original error"):
            execute_workflow(wf, ctx, registry=reg)


def test_on_error_none_reraises() -> None:
    from solux.workflows.engine import execute_workflow

    def failing_handler(ctx: Context, step: Step) -> Context:
        raise RuntimeError("unhandled")

    reg = StepRegistry()
    reg.register("test.fail", failing_handler)

    wf = Workflow(
        name="no_on_error",
        description="",
        steps=[Step(name="risky", type="test.fail")],
    )

    ctx = _ctx()
    with pytest.raises(RuntimeError, match="unhandled"):
        execute_workflow(wf, ctx, registry=reg)


# ---------------------------------------------------------------------------
# Parallel foreach
# ---------------------------------------------------------------------------


def test_parallel_foreach_runs_all_items() -> None:
    from solux.workflows.engine import execute_workflow

    import threading

    seen = []
    lock = threading.Lock()

    def collect(ctx: Context, step: Step) -> Context:
        with lock:
            seen.append(ctx.data.get("_item"))
        ctx.data["processed"] = ctx.data.get("_item")
        return ctx

    reg = StepRegistry()
    reg.register("test.collect", collect)

    wf = Workflow(
        name="parallel_test",
        description="",
        steps=[
            Step(name="each", type="test.collect", foreach="items", config={"parallel": 3}),
        ],
    )
    ctx = _ctx(data={"items": ["a", "b", "c", "d"]})
    result = execute_workflow(wf, ctx, registry=reg)

    assert sorted(seen) == ["a", "b", "c", "d"]


def test_parallel_foreach_results_collected() -> None:
    from solux.workflows.engine import execute_workflow

    def tag(ctx: Context, step: Step) -> Context:
        ctx.data["tag"] = f"done:{ctx.data.get('_item')}"
        return ctx

    reg = StepRegistry()
    reg.register("test.tag", tag)

    wf = Workflow(
        name="parallel_results",
        description="",
        steps=[
            Step(name="each", type="test.tag", foreach="items", config={"parallel": 2}),
        ],
    )
    ctx = _ctx(data={"items": ["x", "y"]})
    result = execute_workflow(wf, ctx, registry=reg)

    assert ContextKeys.FOREACH_RESULTS in result.data
    foreach_results = result.data[ContextKeys.FOREACH_RESULTS]
    assert len(foreach_results) == 2
    assert foreach_results[0]["tag"] == "done:x"
    assert foreach_results[1]["tag"] == "done:y"


def test_parallel_foreach_zero_is_sequential() -> None:
    from solux.workflows.engine import execute_workflow

    seen = []

    def collect(ctx: Context, step: Step) -> Context:
        seen.append(ctx.data.get("_item"))
        return ctx

    reg = StepRegistry()
    reg.register("test.collect", collect)

    wf = Workflow(
        name="seq_test",
        description="",
        steps=[
            Step(name="each", type="test.collect", foreach="items", config={"parallel": 0}),
        ],
    )
    ctx = _ctx(data={"items": ["a", "b"]})
    execute_workflow(wf, ctx, registry=reg)

    # Sequential preserves order
    assert seen == ["a", "b"]
    # No _foreach_results key (only set by parallel path)
    # (sequential path does not set it)


def test_parallel_foreach_exception_propagates() -> None:
    from solux.workflows.engine import execute_workflow

    def explode(ctx: Context, step: Step) -> Context:
        if ctx.data.get("_item") == "bad":
            raise ValueError("bad item")
        return ctx

    reg = StepRegistry()
    reg.register("test.explode", explode)

    wf = Workflow(
        name="parallel_err",
        description="",
        steps=[
            Step(name="each", type="test.explode", foreach="items", config={"parallel": 2}),
        ],
    )
    ctx = _ctx(data={"items": ["ok", "bad", "ok2"]})
    with pytest.raises(ValueError, match="bad item"):
        execute_workflow(wf, ctx, registry=reg)


# ---------------------------------------------------------------------------
# Loader: on_error parsing and serialization
# ---------------------------------------------------------------------------


def test_loader_parses_on_error_field() -> None:
    from solux.workflows.loader import _parse_step

    raw = {"name": "risky", "type": "test.step", "config": {}, "on_error": "recovery"}
    step = _parse_step(raw, 0, interpolate_secrets=False)
    assert step.on_error == "recovery"


def test_loader_on_error_none_by_default() -> None:
    from solux.workflows.loader import _parse_step

    raw = {"name": "normal", "type": "test.step", "config": {}}
    step = _parse_step(raw, 0, interpolate_secrets=False)
    assert step.on_error is None


def test_loader_on_error_non_string_raises() -> None:
    from solux.workflows.loader import WorkflowLoadError, _parse_step

    raw = {"name": "bad", "type": "test.step", "config": {}, "on_error": 123}
    with pytest.raises(WorkflowLoadError, match="on_error must be a string"):
        _parse_step(raw, 0, interpolate_secrets=False)


def test_workflow_to_dict_includes_on_error() -> None:
    from solux.workflows.loader import workflow_to_dict

    wf = Workflow(
        name="test",
        description="",
        steps=[Step(name="s1", type="t1", on_error="fallback")],
    )
    d = workflow_to_dict(wf)
    assert d["steps"][0]["on_error"] == "fallback"


def test_workflow_to_dict_omits_on_error_when_none() -> None:
    from solux.workflows.loader import workflow_to_dict

    wf = Workflow(
        name="test",
        description="",
        steps=[Step(name="s1", type="t1")],
    )
    d = workflow_to_dict(wf)
    assert "on_error" not in d["steps"][0]

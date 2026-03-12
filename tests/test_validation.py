from __future__ import annotations

from solus.workflows.loader import load_workflow
from solus.workflows.models import Step, Workflow
from solus.workflows.registry import global_registry
from solus.workflows.validation import ValidationResult, validate_workflow


def test_valid_audio_summary_workflow() -> None:
    wf = load_workflow("audio_summary")
    result = validate_workflow(wf)
    assert result.valid is True
    errors = [i for i in result.issues if i.level == "error"]
    assert errors == []


def test_valid_webpage_summary_workflow() -> None:
    wf = load_workflow("webpage_summary")
    result = validate_workflow(wf)
    assert result.valid is True
    errors = [i for i in result.issues if i.level == "error"]
    assert errors == []


def test_unknown_step_type_is_error() -> None:
    wf = Workflow(
        name="bad",
        description="broken workflow",
        steps=[Step(name="boom", type="no.such.step", config={})],
    )
    result = validate_workflow(wf)
    assert result.valid is False
    assert len(result.issues) == 1
    assert result.issues[0].level == "error"
    assert "unknown step type" in result.issues[0].message


def test_missing_read_key_is_warning() -> None:
    wf = Workflow(
        name="missing_key",
        description="",
        steps=[
            Step(name="summarize", type="ai.llm_summarize", config={}),
        ],
    )
    result = validate_workflow(wf)
    assert result.valid is True
    warnings = [i for i in result.issues if i.level == "warning"]
    assert any("transcript_text" in w.message for w in warnings)


def test_validation_result_valid_with_warnings() -> None:
    wf = Workflow(
        name="warn_only",
        description="",
        steps=[
            Step(name="write", type="output.file_write", config={}),
        ],
    )
    result = validate_workflow(wf)
    assert result.valid is True
    assert len(result.issues) > 0
    assert all(i.level == "warning" for i in result.issues)


def test_effective_reads_resolves_input_key() -> None:
    wf = Workflow(
        name="resolved",
        description="",
        steps=[
            Step(name="summarize", type="ai.llm_summarize", config={"input_key": "webpage_text"}),
        ],
    )
    result = validate_workflow(wf)
    warnings = [i for i in result.issues if i.level == "warning"]
    # Should warn about webpage_text (the resolved key), not transcript_text (the default)
    warned_keys = [w.message for w in warnings]
    assert any("webpage_text" in m for m in warned_keys)
    assert not any("transcript_text" in m for m in warned_keys)


def test_validation_skips_runtime_keys() -> None:
    # source_fetch reads runtime.no_cache, runtime.verbose, runtime.progress
    # These should not trigger warnings
    wf = Workflow(
        name="runtime_test",
        description="",
        steps=[
            Step(name="fetch", type="input.source_fetch", config={}),
        ],
    )
    result = validate_workflow(wf)
    warnings = [i for i in result.issues if i.level == "warning"]
    runtime_warnings = [w for w in warnings if "runtime." in w.message]
    assert runtime_warnings == []


def test_validation_when_step_emits_warning() -> None:
    wf = Workflow(
        name="when_test",
        description="",
        steps=[
            Step(name="cond_write", type="output.file_write", config={}, when="some_key is not None"),
        ],
    )
    result = validate_workflow(wf)
    warnings = [i for i in result.issues if i.level == "warning"]
    when_warnings = [w for w in warnings if "'when' expression" in w.message]
    assert len(when_warnings) == 1
    assert "some_key is not None" in when_warnings[0].message


def test_validation_foreach_step_emits_warning_and_injects_keys() -> None:
    wf = Workflow(
        name="foreach_test",
        description="",
        steps=[
            Step(name="each_write", type="output.file_write", config={}, foreach="items"),
        ],
    )
    result = validate_workflow(wf)
    warnings = [i for i in result.issues if i.level == "warning"]
    foreach_warnings = [w for w in warnings if "foreach" in w.message]
    assert len(foreach_warnings) == 1
    assert "items" in foreach_warnings[0].message


def test_validation_flags_trusted_only_in_untrusted_mode() -> None:
    from solus.modules.spec import ModuleSpec
    from solus.workflows.registry import StepRegistry

    def dummy(ctx, step):
        return ctx

    spec = ModuleSpec(
        name="danger",
        version="0.1.0",
        category="output",
        description="dangerous",
        handler=dummy,
        safety="trusted_only",
    )
    reg = StepRegistry()
    reg.register(spec.step_type, spec.handler, spec=spec)

    wf = Workflow(
        name="sec_test",
        description="",
        steps=[Step(name="danger_step", type=spec.step_type, config={})],
    )
    result = validate_workflow(wf, registry=reg, security_mode="untrusted")
    assert result.valid is False
    errors = [i for i in result.issues if i.level == "error"]
    assert any("trusted-only" in e.message for e in errors)


def test_validation_allows_trusted_only_in_trusted_mode() -> None:
    from solus.modules.spec import ModuleSpec
    from solus.workflows.registry import StepRegistry

    def dummy(ctx, step):
        return ctx

    spec = ModuleSpec(
        name="danger",
        version="0.1.0",
        category="output",
        description="dangerous",
        handler=dummy,
        safety="trusted_only",
    )
    reg = StepRegistry()
    reg.register(spec.step_type, spec.handler, spec=spec)

    wf = Workflow(
        name="sec_test",
        description="",
        steps=[Step(name="danger_step", type=spec.step_type, config={})],
    )
    result = validate_workflow(wf, registry=reg, security_mode="trusted")
    security_errors = [i for i in result.issues if i.level == "error" and "trusted-only" in i.message]
    assert security_errors == []


def test_validation_blocks_network_module_in_untrusted_mode() -> None:
    from solus.modules.spec import ModuleSpec
    from solus.workflows.registry import StepRegistry

    def dummy(ctx, step):
        return ctx

    spec = ModuleSpec(
        name="network_mod",
        version="0.1.0",
        category="input",
        description="networked",
        handler=dummy,
        safety="safe",
        network=True,
    )
    reg = StepRegistry()
    reg.register(spec.step_type, spec.handler, spec=spec)

    wf = Workflow(
        name="sec_network_test",
        description="",
        steps=[Step(name="network_step", type=spec.step_type, config={})],
    )
    result = validate_workflow(wf, registry=reg, security_mode="untrusted")
    assert result.valid is False
    errors = [i for i in result.issues if i.level == "error"]
    assert any("network-enabled module" in e.message for e in errors)


def test_validation_rejects_timeout_for_network_module() -> None:
    wf = Workflow(
        name="timeout_network",
        description="",
        steps=[Step(name="prompt", type="ai.llm_prompt", config={"input_key": "input_text"}, timeout_seconds=5)],
    )
    result = validate_workflow(wf)
    assert result.valid is False
    errors = [i for i in result.issues if i.level == "error"]
    assert any("timeout=5" in e.message and "network-enabled module" in e.message for e in errors)


def test_validation_rejects_timeout_for_trusted_only_module() -> None:
    wf = Workflow(
        name="timeout_trusted_only",
        description="",
        steps=[Step(name="webhook", type="output.webhook", config={"url": "https://example.com"}, timeout_seconds=5)],
    )
    result = validate_workflow(wf)
    assert result.valid is False
    errors = [i for i in result.issues if i.level == "error"]
    assert any("timeout=5" in e.message and "trusted-only module" in e.message for e in errors)


def test_validation_on_error_emits_warning() -> None:
    wf = Workflow(
        name="on_error_test",
        description="",
        steps=[
            Step(name="risky", type="output.file_write", config={}, on_error="recovery_workflow"),
        ],
    )
    result = validate_workflow(wf)
    warnings = [i for i in result.issues if i.level == "warning"]
    on_error_warnings = [w for w in warnings if "on_error" in w.message]
    assert len(on_error_warnings) == 1
    assert "recovery_workflow" in on_error_warnings[0].message
    # on_error is a warning, not an error — workflow should still be valid
    assert result.valid is True


def test_validation_foreach_injects_item_index_for_downstream() -> None:
    from solus.workflows.registry import StepRegistry, global_registry
    from solus.modules.spec import ModuleSpec, ContextKey

    # Use the global_registry (which has output.file_write) and add a custom reader
    def dummy(ctx, step):
        return ctx

    spec_reads_item = ModuleSpec(
        name="item_reader",
        version="1.0",
        category="transform",
        description="reads _item",
        handler=dummy,
        reads=(ContextKey("_item", "iteration item"),),
    )

    # Build a registry with both the real file_write and our custom reader
    from solus.modules.discovery import discover_modules

    reg = StepRegistry()
    for spec in discover_modules():
        reg.register(spec.step_type, spec.handler, spec=spec)
        for alias in spec.aliases:
            reg.register(alias, spec.handler, spec=spec)
    reg.register("transform.item_reader", dummy, spec=spec_reads_item)

    wf = Workflow(
        name="item_test",
        description="",
        steps=[
            Step(name="each", type="output.file_write", config={}, foreach="items"),
            Step(name="read_item", type="transform.item_reader", config={}),
        ],
    )
    result = validate_workflow(wf, registry=reg)
    # _item should now be available — the item_reader step should not emit a "not available" warning
    key_warnings = [i for i in result.issues if "not be available" in i.message and "_item" in i.message]
    assert key_warnings == []

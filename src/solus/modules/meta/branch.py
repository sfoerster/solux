from __future__ import annotations

from solus.modules.spec import ConfigField, ModuleSpec
from solus.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    from solus.workflows.engine import execute_workflow
    from solus.workflows.loader import WorkflowLoadError, load_workflow
    from solus.workflows.registry import StepRegistry

    condition_key = str(step.config.get("condition_key", "")).strip()
    if not condition_key:
        raise RuntimeError("meta.branch: 'condition_key' config is required")

    branches = step.config.get("branches")
    if not isinstance(branches, dict) or not branches:
        raise RuntimeError("meta.branch: 'branches' config must be a non-empty mapping of value -> workflow name")

    default = step.config.get("default")
    if default is not None:
        default = str(default).strip()

    value = str(ctx.data.get(condition_key, ""))
    target_workflow = branches.get(value)

    if target_workflow is None:
        if default is not None:
            target_workflow = default
        else:
            raise RuntimeError(
                f"meta.branch: no branch matched value '{value}' for key '{condition_key}' "
                f"and no default workflow configured"
            )

    target_workflow = str(target_workflow).strip()

    # Cycle detection via shared subworkflow stack
    call_stack: list[str] = list(ctx.data.get("_subworkflow_stack", []))
    if target_workflow in call_stack:
        cycle = " -> ".join(call_stack + [target_workflow])
        raise RuntimeError(f"meta.branch: circular workflow reference detected: {cycle}")

    workflow_dir = getattr(ctx.config, "workflows_dir", None)
    _strict = getattr(getattr(ctx.config, "security", None), "strict_env_vars", False)
    try:
        sub_workflow = load_workflow(target_workflow, workflow_dir=workflow_dir, strict_secrets=_strict)
    except WorkflowLoadError as exc:
        raise RuntimeError(f"meta.branch: could not load workflow '{target_workflow}': {exc}") from exc

    ctx.logger.info("meta.branch: routing to workflow '%s' (key=%s, value=%s)", target_workflow, condition_key, value)
    ctx.data["_subworkflow_stack"] = call_stack + [target_workflow]
    active_registry = getattr(ctx, "_active_registry", None)
    if isinstance(active_registry, StepRegistry):
        result_ctx = execute_workflow(sub_workflow, ctx, registry=active_registry)
    else:
        result_ctx = execute_workflow(sub_workflow, ctx)
    result_ctx.data["_subworkflow_stack"] = call_stack
    ctx.logger.info("meta.branch: workflow '%s' complete", target_workflow)
    return result_ctx


MODULE = ModuleSpec(
    name="branch",
    version="0.1.0",
    category="meta",
    description="Conditional routing: select a workflow to execute based on a context value.",
    handler=handle,
    step_type="branch",
    config_schema=(
        ConfigField(name="condition_key", description="Context key whose value selects the branch", required=True),
        ConfigField(
            name="branches",
            description="Mapping of value -> workflow name",
            type="dict",
            required=True,
        ),
        ConfigField(name="default", description="Fallback workflow name when no branch matches", required=False),
    ),
    reads=(),
    writes=(),
)

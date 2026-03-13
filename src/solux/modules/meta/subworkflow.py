from __future__ import annotations

from solux.modules.spec import ConfigField, ModuleSpec
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    from solux.workflows.engine import execute_workflow
    from solux.workflows.loader import WorkflowLoadError, load_workflow
    from solux.workflows.registry import StepRegistry

    name = str(step.config.get("name", "")).strip()
    if not name:
        raise RuntimeError("meta.subworkflow: 'name' config is required")

    # Cycle detection: track the active call stack in ctx.data.
    call_stack: list[str] = list(ctx.data.get("_subworkflow_stack", []))
    if name in call_stack:
        cycle = " -> ".join(call_stack + [name])
        raise RuntimeError(f"meta.subworkflow: circular sub-workflow reference detected: {cycle}")

    workflow_dir = getattr(ctx.config, "workflows_dir", None)
    _strict = getattr(getattr(ctx.config, "security", None), "strict_env_vars", False)
    try:
        sub_workflow = load_workflow(name, workflow_dir=workflow_dir, strict_secrets=_strict)
    except WorkflowLoadError as exc:
        raise RuntimeError(f"meta.subworkflow: could not load sub-workflow '{name}': {exc}") from exc

    ctx.logger.info("meta.subworkflow: executing sub-workflow '%s'", name)
    ctx.data["_subworkflow_stack"] = call_stack + [name]
    active_registry = getattr(ctx, "_active_registry", None)
    if isinstance(active_registry, StepRegistry):
        result_ctx = execute_workflow(sub_workflow, ctx, registry=active_registry)
    else:
        result_ctx = execute_workflow(sub_workflow, ctx)
    # Restore call stack depth after returning from the sub-workflow.
    result_ctx.data["_subworkflow_stack"] = call_stack
    ctx.logger.info("meta.subworkflow: sub-workflow '%s' complete", name)
    return result_ctx


MODULE = ModuleSpec(
    name="subworkflow",
    version="0.1.0",
    category="meta",
    description="Execute another named workflow as a step (sub-workflow composition).",
    handler=handle,
    step_type="workflow",
    config_schema=(ConfigField(name="name", description="Name of the workflow to execute", required=True),),
    reads=(),
    writes=(),
)

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable

from .expr import evaluate_when
from .models import Context, ContextKeys, Workflow
from .registry import StepRegistry, global_registry
from .validation import validate_workflow

logger = logging.getLogger(__name__)

_FOREACH_MAX_ITEMS = 10_000


class StepTimeoutError(RuntimeError):
    """Raised when a workflow step exceeds its configured timeout."""


def _evaluate_when_for_step(
    expr: str,
    data: dict,
    step_type: str,
    registry: StepRegistry,
) -> bool:
    """Evaluate a when: expression, fail-closed for trusted_only steps."""
    spec = registry.get_spec(step_type)
    if spec is not None and spec.safety == "trusted_only":
        # Fail-closed: if the expression errors, skip the step
        try:
            import ast as _ast
            from .expr import _check_safe, _eval_node

            tree = _ast.parse(expr.strip(), mode="eval")
            _check_safe(tree)
            return bool(_eval_node(tree, data))
        except Exception as exc:
            logger.warning(
                "when: expression %r failed for trusted_only step %s: %s; skipping step",
                expr,
                step_type,
                exc,
            )
            return False
    # For safe steps, delegate to existing fail-open evaluator
    return evaluate_when(expr, data)


def _enforce_step_safety(ctx: Context, step_type: str, step_name: str, registry: StepRegistry) -> None:
    spec = registry.get_spec(step_type)
    mode = str(getattr(getattr(ctx.config, "security", None), "mode", "trusted")).lower()
    if spec is None:
        if mode == "untrusted":
            raise RuntimeError(
                f"Step '{step_name}' ({step_type}) has no module spec and cannot be verified as safe in untrusted mode."
            )
        return
    if mode == "untrusted" and spec.safety == "trusted_only":
        raise RuntimeError(
            f"Step '{step_name}' ({step_type}) uses trusted-only module '{spec.name}' but security.mode is 'untrusted'."
        )
    if mode == "untrusted" and spec.network:
        raise RuntimeError(
            f"Step '{step_name}' ({step_type}) uses network-enabled module '{spec.name}' "
            "but security.mode is 'untrusted'."
        )


def _run_step_with_optional_timeout(
    fn,
    *,
    step_name: str,
    step_type: str,
    timeout_seconds: int | None,
):
    if timeout_seconds is None:
        return fn()

    result_box: list = []
    error_box: list[BaseException] = []

    def _target() -> None:
        try:
            result_box.append(fn())
        except BaseException as exc:
            error_box.append(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        # The daemon thread will be abandoned and cleaned up at process exit.
        # Python cannot force-kill threads, but daemon=True ensures they do not
        # prevent interpreter shutdown.
        logger.warning(
            "Step '%s' (%s) timed out after %ds; orphaned daemon thread will be reclaimed at process exit",
            step_name,
            step_type,
            timeout_seconds,
        )
        raise StepTimeoutError(f"Step '{step_name}' ({step_type}) timed out after {timeout_seconds}s")

    if error_box:
        raise error_box[0]

    return result_box[0] if result_box else None


def _run_parallel_foreach(ctx: Context, step, handler, items: list, max_workers: int) -> Context:
    """Execute foreach iterations in parallel using a thread pool."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[tuple[int, dict]] = [None] * len(items)  # type: ignore[list-item]

    def _run_one(index: int, item):
        sub_data = {**ctx.data, ContextKeys.FOREACH_ITEM: item, ContextKeys.FOREACH_INDEX: index}
        sub_ctx = replace(ctx, data=sub_data)
        sub_ctx = handler(sub_ctx, step)
        return index, sub_ctx.data

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, i, item): i for i, item in enumerate(items)}
        for future in as_completed(futures):
            idx, data = future.result()
            results[idx] = (idx, data)

    # Collect all iteration results and apply last iteration's data as final
    foreach_results = [data for _, data in results]
    final_data = dict(results[-1][1]) if results else dict(ctx.data)
    final_data[ContextKeys.FOREACH_RESULTS] = foreach_results
    final_data.pop(ContextKeys.FOREACH_ITEM, None)
    final_data.pop(ContextKeys.FOREACH_INDEX, None)
    return replace(ctx, data=final_data)


def _handle_on_error(ctx: Context, step, original_exc: Exception, registry: StepRegistry) -> Context:
    """Run the on_error workflow when a step fails. Returns updated context on success."""
    from .loader import WorkflowLoadError, load_workflow

    ctx.logger.warning(
        "step '%s' failed: %s; running on_error workflow '%s'",
        step.name,
        original_exc,
        step.on_error,
    )
    ctx.data[ContextKeys.ERROR] = str(original_exc)
    ctx.data[ContextKeys.ERROR_STEP] = step.name

    workflow_dir = getattr(ctx.config, "workflows_dir", None)
    _strict = getattr(getattr(ctx.config, "security", None), "strict_env_vars", False)
    try:
        error_wf = load_workflow(step.on_error, workflow_dir=workflow_dir, strict_secrets=_strict)
    except WorkflowLoadError as exc:
        ctx.logger.error("on_error: could not load workflow '%s': %s", step.on_error, exc)
        raise original_exc from exc

    try:
        result_ctx = execute_workflow(error_wf, ctx, registry=registry)
    except Exception as error_wf_exc:
        ctx.logger.error("on_error: error workflow '%s' also failed: %s", step.on_error, error_wf_exc)
        raise original_exc from error_wf_exc

    ctx.logger.info("on_error: workflow '%s' completed successfully; continuing", step.on_error)
    return result_ctx


def execute_workflow(
    workflow: Workflow,
    ctx: Context,
    registry: StepRegistry | None = None,
    on_step_complete: "Callable[[Context, str, int, int], None] | None" = None,
) -> Context:
    active_registry = registry or global_registry
    setattr(ctx, "_active_registry", active_registry)

    security_mode = str(getattr(getattr(ctx.config, "security", None), "mode", "trusted")).lower()
    result = validate_workflow(workflow, active_registry, security_mode=security_mode)
    for issue in result.issues:
        if issue.level == "error":
            ctx.logger.error("validation: step '%s': %s", issue.step_name, issue.message)
        else:
            ctx.logger.warning("validation: step '%s': %s", issue.step_name, issue.message)
    if not result.valid:
        error_count = sum(1 for i in result.issues if i.level == "error")
        raise RuntimeError(f"Workflow '{workflow.name}' failed validation with {error_count} error(s)")

    if ContextKeys.STEP_TIMINGS not in ctx.data:
        ctx.data[ContextKeys.STEP_TIMINGS] = []

    current = ctx
    for step_index, step in enumerate(workflow.steps):
        # Conditional skip
        if step.when is not None:
            if not _evaluate_when_for_step(step.when, current.data, step.type, active_registry):
                current.logger.info("step.skip name=%s (when=%r false)", step.name, step.when)
                continue

        _enforce_step_safety(current, step.type, step.name, active_registry)
        spec = active_registry.get_spec(step.type)
        if step.timeout_seconds is not None and spec is not None and (spec.safety == "trusted_only" or spec.network):
            mode_label = "trusted-only" if spec.safety == "trusted_only" else "network-enabled"
            raise RuntimeError(
                f"Step '{step.name}' ({step.type}) timeout is not supported for {mode_label} module '{spec.name}'."
            )
        handler = active_registry.get(step.type)
        current.logger.info("step.start name=%s type=%s", step.name, step.type)
        t_start = time.monotonic()

        try:
            if step.foreach is not None:
                items = current.data.get(step.foreach, [])
                if not isinstance(items, (list, tuple)):
                    items = []
                if len(items) > _FOREACH_MAX_ITEMS:
                    raise RuntimeError(
                        f"Step '{step.name}' foreach over '{step.foreach}' has {len(items)} items "
                        f"which exceeds the maximum of {_FOREACH_MAX_ITEMS}"
                    )
                current.logger.info("step.foreach name=%s type=%s items=%d", step.name, step.type, len(items))

                parallel = int(step.config.get("parallel", 0))
                if parallel > 0 and len(items) > 0:
                    current = _run_parallel_foreach(current, step, handler, items, parallel)
                else:

                    def _run_foreach():
                        current_local = current
                        for i, item in enumerate(items):
                            sub_data = {
                                **current_local.data,
                                ContextKeys.FOREACH_ITEM: item,
                                ContextKeys.FOREACH_INDEX: i,
                            }
                            sub_ctx = replace(current_local, data=sub_data)
                            sub_ctx = handler(sub_ctx, step)
                            current_local = replace(current_local, data=sub_ctx.data)
                        return current_local

                    current = _run_step_with_optional_timeout(
                        _run_foreach,
                        step_name=step.name,
                        step_type=step.type,
                        timeout_seconds=step.timeout_seconds,
                    )
            else:
                current = _run_step_with_optional_timeout(
                    lambda: handler(current, step),
                    step_name=step.name,
                    step_type=step.type,
                    timeout_seconds=step.timeout_seconds,
                )
        except Exception as step_exc:
            if step.on_error is not None:
                current = _handle_on_error(current, step, step_exc, active_registry)
            else:
                raise

        t_end = time.monotonic()
        duration_ms = int((t_end - t_start) * 1000)
        timings = list(current.data.get(ContextKeys.STEP_TIMINGS, []))
        timings.append(
            {
                "name": step.name,
                "type": step.type,
                "start": t_start,
                "end": t_end,
                "duration_ms": duration_ms,
            }
        )
        current.data[ContextKeys.STEP_TIMINGS] = timings
        current.logger.info("step.end name=%s type=%s duration_ms=%d", step.name, step.type, duration_ms)

        if on_step_complete is not None:
            try:
                on_step_complete(current, step.name, step_index + 1, len(workflow.steps))
            except Exception:
                pass

        # Post-step schema validation: warn if expected writes are missing
        post_spec = active_registry.get_spec(step.type)
        if post_spec is not None:
            for ctx_key in post_spec.writes:
                if ctx_key.key not in current.data and not ctx_key.key.startswith("_"):
                    current.logger.warning(
                        "step '%s' (%s): expected write key '%s' not found in context after execution",
                        step.name,
                        step.type,
                        ctx_key.key,
                    )

    return current

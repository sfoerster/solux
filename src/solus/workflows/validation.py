from __future__ import annotations

from dataclasses import dataclass

from .models import ContextKeys, Workflow
from .registry import StepRegistry, global_registry


@dataclass(frozen=True)
class ValidationIssue:
    step_name: str
    step_index: int
    level: str  # "error" or "warning"
    message: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool  # True when zero errors (warnings OK)
    issues: list[ValidationIssue]


def validate_workflow(
    workflow: Workflow,
    registry: StepRegistry | None = None,
    security_mode: str | None = None,
) -> ValidationResult:
    active_registry = registry or global_registry
    available_keys: set[str] = {"workflow_name", "runtime"}
    issues: list[ValidationIssue] = []
    has_error = False

    for index, step in enumerate(workflow.steps):
        # Check handler exists
        if step.type not in active_registry.step_types():
            issues.append(
                ValidationIssue(
                    step_name=step.name,
                    step_index=index,
                    level="error",
                    message=f"unknown step type '{step.type}'",
                )
            )
            has_error = True
            continue

        spec = active_registry.get_spec(step.type)
        if spec is None:
            continue

        # Flag trusted_only steps in untrusted security mode
        if security_mode == "untrusted" and spec.safety == "trusted_only":
            issues.append(
                ValidationIssue(
                    step_name=step.name,
                    step_index=index,
                    level="error",
                    message=f"step uses trusted-only module '{spec.name}' but security.mode is 'untrusted'",
                )
            )
            has_error = True

        # In untrusted mode, deny modules that require outbound network access.
        if security_mode == "untrusted" and spec.network:
            issues.append(
                ValidationIssue(
                    step_name=step.name,
                    step_index=index,
                    level="error",
                    message=f"step uses network-enabled module '{spec.name}' but security.mode is 'untrusted'",
                )
            )
            has_error = True

        if step.timeout_seconds is not None and (spec.safety == "trusted_only" or spec.network):
            mode_label = "trusted-only" if spec.safety == "trusted_only" else "network-enabled"
            issues.append(
                ValidationIssue(
                    step_name=step.name,
                    step_index=index,
                    level="error",
                    message=(
                        f"step config timeout={step.timeout_seconds} is not supported for "
                        f"{mode_label} module '{spec.name}'"
                    ),
                )
            )
            has_error = True

        # Compute effective reads: resolve input_key overrides
        effective_reads: list[str] = []
        input_key_default: str | None = None
        input_key_value: str | None = None
        for cf in spec.config_schema:
            if cf.name == "input_key" and cf.default is not None:
                input_key_default = str(cf.default)
                input_key_value = str(step.config.get("input_key", cf.default))
                break

        for ck in spec.reads:
            key = ck.key
            if input_key_default is not None and key == input_key_default and input_key_value is not None:
                key = input_key_value
            effective_reads.append(key)

        # Check reads against available keys
        for key in effective_reads:
            if key.startswith("runtime.") or key == "source":
                continue
            if key not in available_keys:
                issues.append(
                    ValidationIssue(
                        step_name=step.name,
                        step_index=index,
                        level="warning",
                        message=f"key '{key}' may not be available",
                    )
                )

        # Add writes to available keys
        for ck in spec.writes:
            available_keys.add(ck.key)

        # foreach steps inject _item and _index into available keys for downstream steps
        if step.foreach is not None:
            available_keys.add(ContextKeys.FOREACH_ITEM)
            available_keys.add(ContextKeys.FOREACH_INDEX)
            issues.append(
                ValidationIssue(
                    step_name=step.name,
                    step_index=index,
                    level="warning",
                    message=f"foreach step iterates over '{step.foreach}'; key references in 'when' are not statically verified",
                )
            )

        # on_error: warn that the referenced workflow name cannot be statically verified
        if step.on_error is not None:
            issues.append(
                ValidationIssue(
                    step_name=step.name,
                    step_index=index,
                    level="warning",
                    message=f"on_error references workflow '{step.on_error}' which cannot be statically verified",
                )
            )

        # when expressions: warn that key references are not statically verified
        if step.when is not None:
            issues.append(
                ValidationIssue(
                    step_name=step.name,
                    step_index=index,
                    level="warning",
                    message=f"'when' expression {step.when!r} key references are not statically verified",
                )
            )

    return ValidationResult(valid=not has_error, issues=issues)

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from solux.workflows.registry import StepHandler
else:
    # Avoid runtime import cycle between modules.spec <-> workflows.registry.
    StepHandler = Callable[..., Any]


@dataclass(frozen=True)
class Dependency:
    """External binary or service a module requires."""

    name: str
    kind: str = "binary"  # "binary" or "service"
    check_cmd: tuple[str, ...] = ()
    hint: str = ""


@dataclass(frozen=True)
class ConfigField:
    """Accepted config key for a module step."""

    name: str
    description: str = ""
    type: str = "str"
    default: Any = None
    required: bool = False


@dataclass(frozen=True)
class ContextKey:
    """Documents a key a module reads from or writes to the context data dict."""

    key: str
    description: str = ""


@dataclass(frozen=True)
class ModuleSpec:
    """Self-describing wrapper around a step handler."""

    name: str
    version: str
    category: str
    description: str
    handler: StepHandler

    step_type: str = ""
    aliases: tuple[str, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    config_schema: tuple[ConfigField, ...] = ()
    reads: tuple[ContextKey, ...] = ()
    writes: tuple[ContextKey, ...] = ()
    safety: str = "safe"  # "safe" | "trusted_only"
    network: bool = False

    def __post_init__(self) -> None:
        if not self.step_type:
            object.__setattr__(self, "step_type", f"{self.category}.{self.name}")
        if self.safety not in {"safe", "trusted_only"}:
            raise ValueError(
                f"Invalid module safety value {self.safety!r} for {self.name}. Expected 'safe' or 'trusted_only'."
            )

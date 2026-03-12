from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Context, Step

if TYPE_CHECKING:
    from solus.modules.spec import ModuleSpec

StepHandler = Callable[[Context, Step], Context]


class StepRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, StepHandler] = {}
        self._specs: dict[str, ModuleSpec] = {}

    def register(self, step_type: str, handler: StepHandler, spec: ModuleSpec | None = None) -> None:
        self._handlers[step_type] = handler
        if spec is not None:
            self._specs[step_type] = spec

    def get(self, step_type: str) -> StepHandler:
        if step_type not in self._handlers:
            known = ", ".join(sorted(self._handlers))
            raise KeyError(f"No step handler registered for '{step_type}'. Known: {known}")
        return self._handlers[step_type]

    def get_spec(self, step_type: str) -> ModuleSpec | None:
        return self._specs.get(step_type)

    def step_types(self) -> list[str]:
        return sorted(self._handlers)


def _register_modules(registry: StepRegistry, *, external_dir: Path | None = None) -> None:
    from solus.modules.discovery import discover_modules

    for spec in discover_modules(external_dir=external_dir):
        registry.register(spec.step_type, spec.handler, spec=spec)
        for alias in spec.aliases:
            registry.register(alias, spec.handler, spec=spec)


def build_registry(*, external_dir: Path | None = None) -> StepRegistry:
    registry = StepRegistry()
    _register_modules(registry, external_dir=external_dir)
    return registry


global_registry = build_registry()

# Register discovered modules at import time.

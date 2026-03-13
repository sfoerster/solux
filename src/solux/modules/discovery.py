from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path

from .spec import ModuleSpec

logger = logging.getLogger(__name__)

CATEGORY_DIRS = ("input", "transform", "ai", "output", "meta")
_MODULES_PACKAGE = "solux.modules"

DEFAULT_EXTERNAL_MODULES_DIR = Path("~/.config/solux/modules.d")


def _is_module_file(path: Path) -> bool:
    return path.suffix == ".py" and not path.name.startswith("_")


def discover_external_modules(modules_dir: Path | None = None) -> list[ModuleSpec]:
    """Scan an external modules directory and return valid ModuleSpec instances."""
    resolved = (modules_dir or DEFAULT_EXTERNAL_MODULES_DIR).expanduser().resolve()
    if not resolved.is_dir():
        return []

    specs: list[ModuleSpec] = []
    for py_file in sorted(resolved.glob("*.py")):
        if not _is_module_file(py_file):
            continue
        module_name = py_file.stem
        fqn = f"solux_ext.{module_name}"
        try:
            file_spec = importlib.util.spec_from_file_location(fqn, py_file)
            if file_spec is None or file_spec.loader is None:
                logger.warning("Could not create import spec for %s", py_file)
                continue
            mod = importlib.util.module_from_spec(file_spec)
            file_spec.loader.exec_module(mod)
        except Exception:
            logger.warning("Failed to import external module %s", py_file, exc_info=True)
            continue

        spec = getattr(mod, "MODULE", None)
        if not isinstance(spec, ModuleSpec):
            logger.warning("External module %s does not export a MODULE: ModuleSpec", py_file)
            continue

        if spec.category not in CATEGORY_DIRS:
            logger.warning(
                "External module %s declares unknown category '%s'; skipping",
                py_file,
                spec.category,
            )
            continue

        specs.append(spec)

    return specs


def discover_modules(*, external_dir: Path | None = None) -> list[ModuleSpec]:
    """Scan category directories and return all valid ModuleSpec instances."""
    modules_dir = Path(__file__).resolve().parent
    specs: list[ModuleSpec] = []

    for category in CATEGORY_DIRS:
        category_dir = modules_dir / category
        if not category_dir.is_dir():
            continue
        for py_file in sorted(category_dir.glob("*.py")):
            if not _is_module_file(py_file):
                continue
            module_name = py_file.stem
            fqn = f"{_MODULES_PACKAGE}.{category}.{module_name}"
            try:
                mod = importlib.import_module(fqn)
            except Exception:
                logger.warning("Failed to import module %s", fqn, exc_info=True)
                continue

            spec = getattr(mod, "MODULE", None)
            if not isinstance(spec, ModuleSpec):
                logger.warning("Module %s does not export a MODULE: ModuleSpec", fqn)
                continue

            if spec.category != category:
                logger.warning(
                    "Module %s declares category '%s' but lives in '%s'; skipping",
                    fqn,
                    spec.category,
                    category,
                )
                continue

            specs.append(spec)

    # Merge external modules — external modules with the same step_type override builtins
    external_specs = discover_external_modules(external_dir)
    if external_specs:
        builtin_by_type = {s.step_type: s for s in specs}
        external_types = {s.step_type for s in external_specs}
        overridden = set(builtin_by_type) & external_types

        # Block safety downgrades: external module cannot override a trusted_only builtin with safe
        blocked: set[str] = set()
        for step_type in overridden:
            builtin = builtin_by_type[step_type]
            ext = next(s for s in external_specs if s.step_type == step_type)
            if builtin.safety == "trusted_only" and ext.safety != "trusted_only":
                logger.warning(
                    "External module '%s' cannot downgrade safety of builtin '%s' "
                    "from 'trusted_only' to '%s'; keeping builtin",
                    ext.name,
                    builtin.name,
                    ext.safety,
                )
                blocked.add(step_type)

        allowed_overrides = overridden - blocked
        if allowed_overrides:
            specs = [s for s in specs if s.step_type not in allowed_overrides]
        specs.extend(s for s in external_specs if s.step_type not in blocked)

    return specs

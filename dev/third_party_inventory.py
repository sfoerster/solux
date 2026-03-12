#!/usr/bin/env python3
from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

_DEP_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


def _load_declared_dependencies(pyproject_path: Path) -> list[str]:
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = payload.get("project", {})
    deps = [str(item) for item in project.get("dependencies", [])]
    for group, items in project.get("optional-dependencies", {}).items():
        for item in items:
            deps.append(f"{item}  # extra:{group}")
    return deps


def _normalize_name(raw: str) -> str | None:
    m = _DEP_NAME_RE.match(raw)
    if not m:
        return None
    return m.group(1).replace("_", "-").lower()


def _license_for_distribution(name: str) -> tuple[str, str]:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return "-", "-"
    meta = dist.metadata
    license_field = str(meta.get("License") or "").strip()
    classifiers = [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    classifier_summary = "; ".join(classifiers[:3])
    return license_field or "-", classifier_summary or "-"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    pyproject_path = root / "pyproject.toml"
    deps = _load_declared_dependencies(pyproject_path)
    seen: set[str] = set()

    print("| Package | Declared As | License Field | License Classifier(s) |")
    print("|---|---|---|---|")

    for raw in deps:
        pkg = _normalize_name(raw.split("#", 1)[0].strip())
        if not pkg or pkg in seen:
            continue
        seen.add(pkg)
        license_field, license_classifiers = _license_for_distribution(pkg)
        print(f"| `{pkg}` | `{raw}` | `{license_field}` | `{license_classifiers}` |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

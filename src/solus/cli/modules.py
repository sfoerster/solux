from __future__ import annotations

import sys

from ..config import ConfigError, effective_external_modules_dir, load_config


def cmd_modules_list() -> int:
    from ..modules.discovery import discover_modules

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    specs = discover_modules(external_dir=effective_external_modules_dir(config))
    if not specs:
        print("No modules discovered.")
        return 0

    by_category: dict[str, list] = {}
    for spec in specs:
        by_category.setdefault(spec.category, []).append(spec)

    for category in sorted(by_category):
        print(f"\n[{category}]")
        for spec in sorted(by_category[category], key=lambda s: s.name):
            aliases = f"  (aliases: {', '.join(spec.aliases)})" if spec.aliases else ""
            print(f"  {spec.step_type}: {spec.description}{aliases}")
    return 0


def cmd_modules_inspect(name: str) -> int:
    from ..modules.discovery import discover_modules

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    specs = discover_modules(external_dir=effective_external_modules_dir(config))
    match = None
    for spec in specs:
        if spec.name == name or spec.step_type == name or name in spec.aliases:
            match = spec
            break

    if match is None:
        known = ", ".join(sorted(s.name for s in specs))
        print(f"Module '{name}' not found. Known: {known}", file=sys.stderr)
        return 1

    print(f"Name:        {match.name}")
    print(f"Version:     {match.version}")
    print(f"Category:    {match.category}")
    print(f"Step type:   {match.step_type}")
    print(f"Description: {match.description}")
    print(f"Safety:      {match.safety}")
    if match.network:
        print("Network:     yes")
    if match.aliases:
        print(f"Aliases:     {', '.join(match.aliases)}")
    if match.dependencies:
        print("Dependencies:")
        for dep in match.dependencies:
            hint = f" ({dep.hint})" if dep.hint else ""
            print(f"  - {dep.name} [{dep.kind}]{hint}")
    if match.config_schema:
        print("Config schema:")
        for cf in match.config_schema:
            default = f" (default: {cf.default!r})" if cf.default is not None else ""
            print(f"  - {cf.name}: {cf.description}{default}")
    if match.reads:
        print("Reads:")
        for ck in match.reads:
            print(f"  - {ck.key}: {ck.description}")
    if match.writes:
        print("Writes:")
        for ck in match.writes:
            print(f"  - {ck.key}: {ck.description}")
    return 0

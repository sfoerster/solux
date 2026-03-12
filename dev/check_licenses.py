#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path


@dataclass(frozen=True)
class DistLicense:
    name: str
    version: str
    license_field: str
    license_classifiers: list[str]
    denied_matches: list[str]


def _load_policy(policy_path: Path) -> tuple[list[str], set[str]]:
    payload = tomllib.loads(policy_path.read_text(encoding="utf-8"))
    deny_patterns = [str(item) for item in payload.get("deny_patterns", [])]
    ignore_packages = {str(item).strip().lower() for item in payload.get("ignore_packages", []) if str(item).strip()}
    return deny_patterns, ignore_packages


def _normalized(name: str) -> str:
    return name.replace("_", "-").strip().lower()


def _collect_license_candidates(dist: metadata.Distribution) -> tuple[str, list[str]]:
    meta = dist.metadata
    license_field = str(meta.get("License") or "").strip()
    classifiers = [
        str(value)
        for value in (meta.get_all("Classifier") or [])
        if isinstance(value, str) and value.startswith("License ::")
    ]
    return license_field, classifiers


def _collect_license_file_texts(dist: metadata.Distribution) -> list[str]:
    texts: list[str] = []
    for item in (dist.files or []):
        item_str = str(item).replace("\\", "/")
        lowered = item_str.lower()
        base = Path(item_str).name.lower()
        looks_like_license = (
            "licenses/" in lowered
            or "license" in base
            or "copying" in base
            or "notice" in base
        )
        if not looks_like_license:
            continue
        try:
            candidate = dist.locate_file(item)
            if not candidate.is_file():
                continue
            content = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not content.strip():
            continue
        # Inspect only the header section where canonical license names are declared.
        texts.append(content[:1_200])
        if len(texts) >= 6:
            break
    return texts


def _matches_denied(text: str, deny_patterns: list[str]) -> list[str]:
    if not text.strip():
        return []
    matches = [pattern for pattern in deny_patterns if re.search(pattern, text, flags=re.IGNORECASE)]
    return sorted(set(matches))


def _inspect_installed_distributions(policy_path: Path) -> list[DistLicense]:
    deny_patterns, ignore_packages = _load_policy(policy_path)
    rows: list[DistLicense] = []

    for dist in metadata.distributions():
        name = _normalized(dist.metadata.get("Name", dist.name if hasattr(dist, "name") else ""))
        if not name or name in ignore_packages:
            continue

        version = dist.version
        license_field, classifiers = _collect_license_candidates(dist)
        license_file_texts = _collect_license_file_texts(dist)
        corpus = "\n".join([license_field, *classifiers, *license_file_texts])
        denied_matches = _matches_denied(corpus, deny_patterns)
        rows.append(
            DistLicense(
                name=name,
                version=version,
                license_field=license_field or "-",
                license_classifiers=classifiers,
                denied_matches=denied_matches,
            )
        )

    rows.sort(key=lambda item: item.name)
    return rows


def _format_markdown(rows: list[DistLicense]) -> str:
    lines = [
        "| Package | Version | License Field | License Classifier(s) | Deny Match |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        classifiers = "<br>".join(row.license_classifiers) if row.license_classifiers else "-"
        denied = ", ".join(row.denied_matches) if row.denied_matches else "-"
        lines.append(
            f"| `{row.name}` | `{row.version}` | `{row.license_field}` | {classifiers} | `{denied}` |"
        )
    return "\n".join(lines) + "\n"


def _format_text(rows: list[DistLicense]) -> str:
    output_lines: list[str] = []
    for row in rows:
        denied = ", ".join(row.denied_matches) if row.denied_matches else "-"
        classifiers = "; ".join(row.license_classifiers) if row.license_classifiers else "-"
        output_lines.append(
            f"{row.name}\t{row.version}\tlicense={row.license_field}\tclassifiers={classifiers}\tdeny={denied}"
        )
    return "\n".join(output_lines) + ("\n" if output_lines else "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check installed Python dependency licenses against a deny policy.")
    parser.add_argument(
        "--policy",
        default="compliance/license_policy.toml",
        help="Path to TOML policy with deny_patterns and ignore_packages.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "markdown"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--fail-on-deny",
        action="store_true",
        help="Exit non-zero if any package matches a deny pattern.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Emit only a summary line to stderr.",
    )
    args = parser.parse_args()

    policy_path = Path(args.policy).resolve()
    if not policy_path.exists():
        print(f"[license-check] policy file not found: {policy_path}", file=sys.stderr)
        return 2

    rows = _inspect_installed_distributions(policy_path)
    denied = [row for row in rows if row.denied_matches]

    if not args.summary:
        if args.format == "markdown":
            print(_format_markdown(rows), end="")
        else:
            print(_format_text(rows), end="")

    print(
        f"[license-check] scanned={len(rows)} denied={len(denied)} policy={policy_path}",
        file=sys.stderr,
    )

    if args.fail_on_deny and denied:
        for row in denied:
            print(
                f"[license-check] denied package: {row.name} {row.version} matches {', '.join(row.denied_matches)}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

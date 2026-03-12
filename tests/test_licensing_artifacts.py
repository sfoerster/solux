from __future__ import annotations

from pathlib import Path
import tomllib


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_core_dependencies_do_not_include_html2text() -> None:
    pyproject_path = _repo_root() / "pyproject.toml"
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    deps = [str(dep).lower() for dep in payload["project"]["dependencies"]]
    assert not any(dep.startswith("html2text") for dep in deps)


def test_license_names_copyright_holder() -> None:
    license_text = (_repo_root() / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright 2026 Steven Foerster" in license_text
    assert "Apache License" in license_text


def test_third_party_notices_present_and_lists_core_runtime_dependencies() -> None:
    notices_text = (_repo_root() / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "requests" in notices_text
    assert "PyYAML" in notices_text
    assert "defusedxml" in notices_text

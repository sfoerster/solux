from __future__ import annotations

import subprocess
from pathlib import Path

from solus.cli.maintenance import cmd_config_edit


def test_cmd_config_edit_supports_editor_with_flags(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    monkeypatch.setattr("solus.cli.maintenance.get_default_config_path", lambda: config_path)
    monkeypatch.setattr("solus.cli.maintenance.ensure_config_file", lambda path: (Path(path), False))
    monkeypatch.setenv("EDITOR", "code --wait")
    monkeypatch.delenv("VISUAL", raising=False)

    seen: dict[str, list[str]] = {}

    def _fake_run(cmd, check=False):
        del check
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("solus.cli.maintenance.subprocess.run", _fake_run)

    rc = cmd_config_edit()
    assert rc == 0
    assert seen["cmd"] == ["code", "--wait", str(config_path)]

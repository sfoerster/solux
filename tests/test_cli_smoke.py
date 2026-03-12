from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from solus.cli import main


def test_solus_help_smoke() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src_dir) if not env.get("PYTHONPATH") else f"{src_dir}{os.pathsep}{env['PYTHONPATH']}"

    solus_bin = shutil.which("solus")
    if solus_bin:
        cmd = [solus_bin, "--help"]
    else:
        cmd = [sys.executable, "-m", "solus.cli", "--help"]

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    assert proc.returncode == 0
    assert "Solus: local-first AI workflow engine." in proc.stdout


def test_run_dry_run_flag(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    rc = main(["run", "--dry-run", "--workflow", "audio_summary", "test.mp3"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "Validation" in captured.out


def test_run_unknown_workflow_returns_error(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    rc = main(["run", "--workflow", "does_not_exist", "episode.mp3", "--quiet-progress"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Workflow 'does_not_exist' not found." in captured.err


def test_run_audio_summary_failure_prints_prereq_hint(monkeypatch, capsys) -> None:
    class _Config:
        config_path = Path("/tmp/config.toml")

    monkeypatch.setattr("solus.cli.run.load_config", lambda: _Config())

    def _raise_process_source(**_kwargs):
        raise RuntimeError("whisper-cli not configured or not found")

    monkeypatch.setattr("solus.cli.run.process_source", _raise_process_source)

    rc = main(["run", "--workflow", "audio_summary", "episode.mp3", "--quiet-progress"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "solus doctor --workflow audio_summary" in captured.err
    assert "webpage_summary" in captured.err

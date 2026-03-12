from __future__ import annotations

from pathlib import Path

from solus.cli import main


def _write_config(tmp_path: Path, *, workflows_dir: Path, triggers_dir: Path) -> None:
    config_dir = tmp_path / ".config" / "solus"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        (f'[workflows]\ndir = "{workflows_dir}"\n\n[triggers]\ndir = "{triggers_dir}"\n'),
        encoding="utf-8",
    )


def test_triggers_validate_fails_when_workflow_missing(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    workflows_dir = tmp_path / "workflows.d"
    triggers_dir = tmp_path / "triggers.d"
    workflows_dir.mkdir()
    triggers_dir.mkdir()
    _write_config(tmp_path, workflows_dir=workflows_dir, triggers_dir=triggers_dir)

    (triggers_dir / "nightly.yaml").write_text(
        ("name: nightly\ntype: cron\nworkflow: missing_flow\nconfig: {}\n"),
        encoding="utf-8",
    )

    rc = main(["triggers", "validate", "nightly"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "INVALID" in captured.err
    assert "referenced workflow does not exist" in captured.err


def test_triggers_validate_succeeds_when_workflow_exists(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    workflows_dir = tmp_path / "workflows.d"
    triggers_dir = tmp_path / "triggers.d"
    workflows_dir.mkdir()
    triggers_dir.mkdir()
    _write_config(tmp_path, workflows_dir=workflows_dir, triggers_dir=triggers_dir)

    (workflows_dir / "my_flow.yaml").write_text(
        ("name: my_flow\ndescription: test\nsteps:\n  - name: clean\n    type: transform.text_clean\n    config: {}\n"),
        encoding="utf-8",
    )
    (triggers_dir / "nightly.yaml").write_text(
        ("name: nightly\ntype: cron\nworkflow: my_flow\nconfig: {}\n"),
        encoding="utf-8",
    )

    rc = main(["triggers", "validate", "nightly"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "VALID" in captured.out

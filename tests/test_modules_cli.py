from __future__ import annotations

import textwrap
from pathlib import Path

from solus.cli import main, parse_args


def test_parse_args_modules_list() -> None:
    args = parse_args(["modules", "list"])
    assert args.command == "modules"
    assert args.modules_action == "list"


def test_parse_args_modules_defaults_to_list() -> None:
    args = parse_args(["modules"])
    assert args.command == "modules"
    assert args.modules_action == "list"


def test_parse_args_modules_inspect() -> None:
    args = parse_args(["modules", "inspect", "source_fetch"])
    assert args.command == "modules"
    assert args.modules_action == "inspect"
    assert args.name == "source_fetch"


def test_modules_list_outputs_all_categories(capsys) -> None:
    rc = main(["modules", "list"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "[input]" in captured.out
    assert "[transform]" in captured.out
    assert "[ai]" in captured.out
    assert "[output]" in captured.out
    assert "source_fetch" in captured.out
    assert "webpage_fetch" in captured.out
    assert "audio_normalize" in captured.out
    assert "whisper_transcribe" in captured.out
    assert "llm_summarize" in captured.out
    assert "file_write" in captured.out
    assert "llm_prompt" in captured.out


def test_modules_inspect_known_module(capsys) -> None:
    rc = main(["modules", "inspect", "source_fetch"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name:        source_fetch" in captured.out
    assert "Category:    input" in captured.out
    assert "Step type:   input.source_fetch" in captured.out


def test_modules_inspect_by_step_type(capsys) -> None:
    rc = main(["modules", "inspect", "ai.llm_summarize"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name:        llm_summarize" in captured.out


def test_modules_inspect_by_alias(capsys) -> None:
    rc = main(["modules", "inspect", "llm.summarize"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name:        llm_summarize" in captured.out


def test_modules_inspect_webpage_fetch(capsys) -> None:
    rc = main(["modules", "inspect", "webpage_fetch"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name:        webpage_fetch" in captured.out
    assert "Category:    input" in captured.out
    assert "Step type:   input.webpage_fetch" in captured.out


def test_modules_inspect_file_write(capsys) -> None:
    rc = main(["modules", "inspect", "file_write"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name:        file_write" in captured.out
    assert "Category:    output" in captured.out
    assert "Step type:   output.file_write" in captured.out


def test_modules_inspect_llm_prompt(capsys) -> None:
    rc = main(["modules", "inspect", "llm_prompt"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name:        llm_prompt" in captured.out
    assert "Category:    ai" in captured.out
    assert "Step type:   ai.llm_prompt" in captured.out
    assert "prompt_template" in captured.out
    assert "input_key" in captured.out
    assert "output_key" in captured.out


def test_modules_inspect_unknown_module(capsys) -> None:
    rc = main(["modules", "inspect", "nonexistent"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_modules_inspect_uses_configured_modules_dir(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    modules_dir = tmp_path / "custom-modules"
    modules_dir.mkdir(parents=True)
    (modules_dir / "extmod.py").write_text(
        textwrap.dedent(
            """\
            from solus.modules.spec import ContextKey, ModuleSpec

            def handle(ctx, step):
                del step
                ctx.data["extmod_ok"] = True
                return ctx

            MODULE = ModuleSpec(
                name="extmod",
                version="0.1.0",
                category="transform",
                description="External module for CLI catalog test.",
                handler=handle,
                writes=(ContextKey("extmod_ok", "marker"),),
            )
            """
        ),
        encoding="utf-8",
    )

    config_dir = tmp_path / ".config" / "solus"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        f'[modules]\ndir = "{modules_dir}"\n',
        encoding="utf-8",
    )

    rc = main(["modules", "inspect", "transform.extmod"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name:        extmod" in captured.out

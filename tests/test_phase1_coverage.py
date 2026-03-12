"""Additional tests for Phase 1 onboarding features.

Covers: _generic_failure_hint, _step_progress_callback, improved _print_dry_run,
init/examples CLI dispatch via parse_args, doctor --fix/--all parser flags,
on_step_complete passthrough in pipeline.
"""

from __future__ import annotations

from pathlib import Path

from solus.cli import parse_args
from solus.cli.run import _generic_failure_hint, _step_progress_callback


# ---------------------------------------------------------------------------
# _generic_failure_hint
# ---------------------------------------------------------------------------


def test_generic_failure_hint_connection_refused():
    exc = RuntimeError("Connection refused to http://localhost:11434")
    hint = _generic_failure_hint(exc)
    assert hint is not None
    assert "ollama serve" in hint


def test_generic_failure_hint_ollama_keyword():
    exc = RuntimeError("Ollama server unavailable")
    hint = _generic_failure_hint(exc)
    assert hint is not None
    assert "ollama serve" in hint


def test_generic_failure_hint_config_not_found():
    exc = RuntimeError("config not found at ~/.config/solus/config.toml")
    hint = _generic_failure_hint(exc)
    assert hint is not None
    assert "solus init" in hint


def test_generic_failure_hint_config_missing():
    exc = RuntimeError("config missing, please create one")
    hint = _generic_failure_hint(exc)
    assert hint is not None
    assert "solus init" in hint


def test_generic_failure_hint_unrelated_error():
    exc = RuntimeError("Something completely unrelated happened")
    hint = _generic_failure_hint(exc)
    assert hint is None


# ---------------------------------------------------------------------------
# _step_progress_callback
# ---------------------------------------------------------------------------


def test_step_progress_callback_prints_to_stderr(capsys):
    from solus.workflows.models import Context

    cb = _step_progress_callback()
    ctx = Context(source="test", source_id="abc", data={}, config=None, logger=None, params={})  # type: ignore[arg-type]
    ctx.data["step_timings"] = [
        {"name": "fetch", "type": "input.webpage_fetch", "duration_ms": 1234, "start": 0, "end": 0},
    ]
    cb(ctx, "fetch", 1, 3)
    captured = capsys.readouterr()
    assert "[1/3]" in captured.err
    assert "fetch" in captured.err
    assert "input.webpage_fetch" in captured.err
    assert "1.2s" in captured.err
    assert "done" in captured.err


def test_step_progress_callback_without_timings(capsys):
    from solus.workflows.models import Context

    cb = _step_progress_callback()
    ctx = Context(source="test", source_id="abc", data={}, config=None, logger=None, params={})  # type: ignore[arg-type]
    cb(ctx, "mystep", 2, 4)
    captured = capsys.readouterr()
    assert "[2/4]" in captured.err
    assert "mystep" in captured.err
    assert "done" in captured.err


# ---------------------------------------------------------------------------
# _print_dry_run: arrows between steps
# ---------------------------------------------------------------------------


def test_print_dry_run_shows_arrows(capsys):
    from solus.cli.run import _print_dry_run
    from solus.workflows.models import Step, Workflow
    from solus.workflows.registry import StepRegistry
    from solus.workflows.validation import ValidationResult

    wf = Workflow(
        name="test_wf",
        description="A test workflow",
        steps=[
            Step(name="step_a", type="input.webpage_fetch", config={}),
            Step(name="step_b", type="ai.llm_summarize", config={}),
        ],
    )
    result = ValidationResult(valid=True, issues=[])
    registry = StepRegistry()

    _print_dry_run(wf, result, registry=registry)
    captured = capsys.readouterr()
    assert "Workflow: test_wf" in captured.out
    assert "A test workflow" in captured.out
    # Arrows should appear between steps (but not after the last)
    assert "|" in captured.out
    assert "v" in captured.out
    assert "Validation: OK" in captured.out


def test_print_dry_run_shows_reads_writes(capsys):
    from solus.cli.run import _print_dry_run
    from solus.modules.spec import ContextKey, ModuleSpec
    from solus.workflows.models import Step, Workflow
    from solus.workflows.registry import StepRegistry
    from solus.workflows.validation import ValidationResult

    registry = StepRegistry()
    registry.register(
        "input.webpage_fetch",
        lambda ctx, step: ctx,
        spec=ModuleSpec(
            name="webpage_fetch",
            version="0.1.0",
            category="input",
            description="",
            handler=lambda ctx, step: ctx,
            reads=(),
            writes=(ContextKey("webpage_text", "Extracted text"),),
        ),
    )

    wf = Workflow(
        name="test_wf",
        description="",
        steps=[
            Step(name="fetch", type="input.webpage_fetch", config={}),
        ],
    )
    result = ValidationResult(valid=True, issues=[])

    _print_dry_run(wf, result, registry=registry)
    captured = capsys.readouterr()
    assert "writes: webpage_text" in captured.out


def test_print_dry_run_single_step_no_arrows(capsys):
    from solus.cli.run import _print_dry_run
    from solus.workflows.models import Step, Workflow
    from solus.workflows.registry import StepRegistry
    from solus.workflows.validation import ValidationResult

    wf = Workflow(
        name="single",
        description="",
        steps=[Step(name="only", type="transform.text_clean", config={})],
    )
    result = ValidationResult(valid=True, issues=[])
    _print_dry_run(wf, result, registry=StepRegistry())
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    # No arrow lines for a single step
    arrow_lines = [ln for ln in lines if ln.strip() in ("|", "v")]
    assert len(arrow_lines) == 0


# ---------------------------------------------------------------------------
# parse_args: new subcommands
# ---------------------------------------------------------------------------


def test_parse_args_init():
    args = parse_args(["init"])
    assert args.command == "init"


def test_parse_args_examples():
    args = parse_args(["examples"])
    assert args.command == "examples"


def test_parse_args_doctor_fix_flag():
    args = parse_args(["doctor", "--fix"])
    assert args.command == "doctor"
    assert args.fix is True


def test_parse_args_doctor_all_flag():
    args = parse_args(["doctor", "--all"])
    assert args.command == "doctor"
    assert args.check_all is True


def test_parse_args_doctor_fix_and_all():
    args = parse_args(["doctor", "--fix", "--all"])
    assert args.fix is True
    assert args.check_all is True


# ---------------------------------------------------------------------------
# CLI dispatch: init and examples via main()
# ---------------------------------------------------------------------------


def test_main_dispatches_init(monkeypatch):
    from solus.cli import main

    called = {"init": False}

    def _fake_init(_args):
        called["init"] = True
        return 0

    monkeypatch.setattr("solus.cli.cmd_init", _fake_init)
    ret = main(["init"])
    assert ret == 0
    assert called["init"]


def test_main_dispatches_examples(monkeypatch, capsys):
    from solus.cli import main

    called = {"examples": False}

    def _fake_examples():
        called["examples"] = True
        return 0

    monkeypatch.setattr("solus.cli.cmd_workflows_examples", _fake_examples)
    ret = main(["examples"])
    assert ret == 0
    assert called["examples"]


# ---------------------------------------------------------------------------
# pipeline.py: on_step_complete passthrough
# ---------------------------------------------------------------------------


def test_process_source_passes_on_step_complete(monkeypatch):
    """Verify process_source forwards on_step_complete to execute_source_workflow."""
    from solus.pipeline import process_source

    captured_kwargs: dict = {}

    def _fake_execute(config, *, source, workflow_name, params, no_cache, verbose, progress, on_step_complete=None):
        captured_kwargs["on_step_complete"] = on_step_complete
        from solus.workflows.models import Context

        return Context(
            source=source,
            source_id="abc",
            data={
                "output_text": "test output",
                "audio_input_path": "/fake",
                "wav_path": "/fake",
                "transcript_path": "/fake",
                "cache_output_path": "/fake",
                "export_output_path": "/fake",
            },
            config=config,
            logger=None,  # type: ignore[arg-type]
            params={},
        )

    monkeypatch.setattr("solus.pipeline.execute_source_workflow", _fake_execute)

    sentinel = object()
    result = process_source(
        config=None,  # type: ignore[arg-type]
        source="test.mp3",
        mode="full",
        output_format="markdown",
        timestamps=False,
        no_cache=False,
        verbose=False,
        on_step_complete=sentinel,  # type: ignore[arg-type]
    )
    assert captured_kwargs["on_step_complete"] is sentinel
    assert result.output_text == "test output"


def test_execute_source_workflow_passes_on_step_complete(monkeypatch):
    """Verify execute_source_workflow forwards on_step_complete to execute_workflow."""
    from solus.config import BinaryConfig, Config, OllamaConfig, PathsConfig, PromptsConfig, WhisperConfig
    from solus.pipeline import execute_source_workflow

    captured_kwargs: dict = {}

    def _fake_execute_workflow(workflow, ctx, registry=None, on_step_complete=None):
        captured_kwargs["on_step_complete"] = on_step_complete
        return ctx

    monkeypatch.setattr("solus.pipeline.execute_workflow", _fake_execute_workflow)

    tmp = Path("/tmp/test_esw")
    cfg = Config(
        paths=PathsConfig(cache_dir=tmp),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="qwen3:8b", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        config_path=tmp / "config.toml",
        config_exists=False,
    )

    sentinel = object()
    execute_source_workflow(
        cfg,
        source="https://example.com",
        workflow_name="webpage_summary",
        on_step_complete=sentinel,  # type: ignore[arg-type]
    )
    assert captured_kwargs["on_step_complete"] is sentinel


# ---------------------------------------------------------------------------
# doctor: colored output
# ---------------------------------------------------------------------------


def test_doctor_print_ok_is_colored_with_force_color(monkeypatch, capsys):
    """Verify _print uses green [OK] when color is forced."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    from solus.doctor import _print

    _print("OK", "test message")
    captured = capsys.readouterr()
    assert "\033[32m[OK]\033[0m" in captured.out
    assert "test message" in captured.out


def test_doctor_print_warn_is_colored_with_force_color(monkeypatch, capsys):
    """Verify _print uses red [!!] when color is forced."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    from solus.doctor import _print

    _print("WARN", "bad thing")
    captured = capsys.readouterr()
    assert "\033[31m[!!]\033[0m" in captured.out


def test_doctor_print_fix_shows_bold_prefix(monkeypatch, capsys):
    """Verify _print with fix=True uses bold 'Fix:' prefix."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    from solus.doctor import _print

    _print("WARN", "missing tool", "install it", fix=True)
    captured = capsys.readouterr()
    assert "Fix:" in captured.out
    assert "install it" in captured.out


def test_doctor_print_no_fix_shows_arrow(monkeypatch, capsys):
    """Verify _print with fix=False uses -> prefix."""
    monkeypatch.setenv("NO_COLOR", "1")
    from solus.doctor import _print

    _print("WARN", "missing tool", "install it", fix=False)
    captured = capsys.readouterr()
    assert "-> install it" in captured.out
    assert "Fix:" not in captured.out


# ---------------------------------------------------------------------------
# Generic failure hint integrated in cmd_run
# ---------------------------------------------------------------------------


def test_run_generic_hint_on_connection_refused(monkeypatch, capsys):
    """cmd_run prints generic Ollama hint when execute_source_workflow raises connection error."""
    from solus.cli import main

    class _Config:
        config_path = Path("/tmp/config.toml")
        security = type("S", (), {"strict_env_vars": False, "mode": "trusted"})()
        ui = type("U", (), {"default_workflow": "webpage_summary"})()

    monkeypatch.setattr("solus.cli.run.load_config", lambda: _Config())

    def _raise(**_kwargs):
        raise RuntimeError("Connection refused to http://localhost:11434")

    monkeypatch.setattr("solus.cli.run.execute_source_workflow", _raise)

    rc = main(["run", "--workflow", "webpage_summary", "https://example.com", "--quiet-progress"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ollama serve" in captured.err

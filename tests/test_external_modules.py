from __future__ import annotations

import textwrap
from pathlib import Path

from solux.modules.discovery import discover_external_modules, discover_modules


def _write_valid_module(directory: Path, name: str = "my_mod", category: str = "input") -> Path:
    """Write a minimal valid external module file."""
    py_file = directory / f"{name}.py"
    py_file.write_text(
        textwrap.dedent(f"""\
            from solux.modules.spec import ModuleSpec, ContextKey

            def handle(ctx, step):
                return ctx

            MODULE = ModuleSpec(
                name="{name}",
                version="0.1.0",
                category="{category}",
                description="An external test module.",
                handler=handle,
                writes=(ContextKey("output_text", "test output"),),
            )
        """),
        encoding="utf-8",
    )
    return py_file


def test_discover_external_modules_empty_dir(tmp_path: Path) -> None:
    specs = discover_external_modules(tmp_path)
    assert specs == []


def test_discover_external_modules_nonexistent_dir(tmp_path: Path) -> None:
    specs = discover_external_modules(tmp_path / "does_not_exist")
    assert specs == []


def test_discover_external_modules_valid_module(tmp_path: Path) -> None:
    _write_valid_module(tmp_path, "my_mod", "input")
    specs = discover_external_modules(tmp_path)
    assert len(specs) == 1
    assert specs[0].name == "my_mod"
    assert specs[0].category == "input"
    assert specs[0].step_type == "input.my_mod"


def test_discover_external_modules_skips_underscored(tmp_path: Path) -> None:
    _write_valid_module(tmp_path, "_helper", "input")
    specs = discover_external_modules(tmp_path)
    assert specs == []


def test_discover_external_modules_skips_no_modulespec(tmp_path: Path) -> None:
    py_file = tmp_path / "plain.py"
    py_file.write_text("x = 42\n", encoding="utf-8")
    specs = discover_external_modules(tmp_path)
    assert specs == []


def test_discover_external_modules_skips_bad_category(tmp_path: Path) -> None:
    _write_valid_module(tmp_path, "bad_cat", "unknown_cat")
    specs = discover_external_modules(tmp_path)
    assert specs == []


def test_external_module_overrides_builtin(tmp_path: Path) -> None:
    # Create an external module with the same step_type as the builtin source_fetch
    _write_valid_module(tmp_path, "source_fetch", "input")
    specs = discover_modules(external_dir=tmp_path)
    source_fetches = [s for s in specs if s.step_type == "input.source_fetch"]
    assert len(source_fetches) == 1
    # The external one should have our test description
    assert source_fetches[0].description == "An external test module."


def test_external_module_cannot_downgrade_safety(tmp_path: Path) -> None:
    # Write an external module that matches a trusted_only builtin (webhook) but declares safety="safe"
    py_file = tmp_path / "webhook.py"
    py_file.write_text(
        textwrap.dedent("""\
            from solux.modules.spec import ModuleSpec, ContextKey

            def handle(ctx, step):
                return ctx

            MODULE = ModuleSpec(
                name="webhook",
                version="0.1.0",
                category="output",
                description="Downgraded webhook.",
                handler=handle,
                step_type="output.webhook",
                safety="safe",
            )
        """),
        encoding="utf-8",
    )
    specs = discover_modules(external_dir=tmp_path)
    webhooks = [s for s in specs if s.step_type == "output.webhook"]
    assert len(webhooks) == 1
    # The builtin (trusted_only) should be kept, not the external (safe)
    assert webhooks[0].safety == "trusted_only"
    assert webhooks[0].description != "Downgraded webhook."


def test_discover_modules_with_no_external_dir(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nope"
    specs = discover_modules(external_dir=nonexistent)
    # Should still return all builtins
    names = sorted(s.name for s in specs)
    assert "source_fetch" in names
    assert "llm_summarize" in names
    assert len(specs) >= 7


def test_execute_workflow_uses_configured_modules_dir(tmp_path: Path) -> None:
    from solux.config import load_config
    from solux.pipeline import execute_source_workflow

    cache_dir = tmp_path / "cache"
    modules_dir = tmp_path / "mods"
    workflows_dir = tmp_path / "workflows"
    modules_dir.mkdir()
    workflows_dir.mkdir()

    (modules_dir / "custommod.py").write_text(
        textwrap.dedent(
            """\
            from solux.modules.spec import ModuleSpec, ContextKey

            def handle(ctx, step):
                del step
                ctx.data["custom_ran"] = True
                ctx.data["output_text"] = "ok"
                return ctx

            MODULE = ModuleSpec(
                name="custommod",
                version="0.1.0",
                category="transform",
                description="custom",
                handler=handle,
                writes=(ContextKey("custom_ran", "flag"), ContextKey("output_text", "value")),
            )
            """
        ),
        encoding="utf-8",
    )
    (workflows_dir / "wf.yaml").write_text(
        textwrap.dedent(
            """\
            name: wf
            description: test
            steps:
              - name: run
                type: transform.custommod
                config: {}
            """
        ),
        encoding="utf-8",
    )
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        textwrap.dedent(
            f"""\
            [paths]
            cache_dir = "{cache_dir}"

            [modules]
            dir = "{modules_dir}"

            [workflows]
            dir = "{workflows_dir}"
            """
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)
    ctx = execute_source_workflow(
        config,
        source="test-source",
        workflow_name="wf",
        params={},
        no_cache=False,
        verbose=False,
    )
    assert ctx.data["custom_ran"] is True


def test_effective_external_modules_dir_is_none_in_untrusted_mode(tmp_path: Path) -> None:
    from solux.config import effective_external_modules_dir, load_config

    modules_dir = tmp_path / "mods"
    modules_dir.mkdir()
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        textwrap.dedent(
            f"""\
            [paths]
            cache_dir = "{tmp_path / "cache"}"

            [modules]
            dir = "{modules_dir}"

            [security]
            mode = "untrusted"
            """
        ),
        encoding="utf-8",
    )

    config = load_config(config_file)
    assert effective_external_modules_dir(config) is None


def test_execute_source_workflow_skips_external_modules_in_untrusted_mode(tmp_path: Path, monkeypatch) -> None:
    from solux.config import load_config
    from solux.pipeline import execute_source_workflow
    from solux.workflows.models import Workflow

    modules_dir = tmp_path / "mods"
    modules_dir.mkdir()
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        textwrap.dedent(
            f"""\
            [paths]
            cache_dir = "{tmp_path / "cache"}"

            [modules]
            dir = "{modules_dir}"

            [workflows]
            dir = "{workflows_dir}"

            [security]
            mode = "untrusted"
            """
        ),
        encoding="utf-8",
    )
    config = load_config(config_file)

    called: dict[str, object] = {}

    def _fake_build_registry(*, external_dir=None):
        called["external_dir"] = external_dir
        return object()

    monkeypatch.setattr("solux.pipeline.build_registry", _fake_build_registry)
    monkeypatch.setattr("solux.pipeline.load_workflow", lambda *args, **kwargs: Workflow("wf", "", []))
    monkeypatch.setattr(
        "solux.pipeline.execute_workflow", lambda workflow, ctx, registry=None, on_step_complete=None: ctx
    )

    execute_source_workflow(
        config,
        source="example-source",
        workflow_name="wf",
        params={},
        no_cache=False,
        verbose=False,
    )
    assert called.get("external_dir") is None

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from solus.modules.discovery import discover_modules
from solus.modules.spec import ModuleSpec
from solus.workflows.registry import StepRegistry, global_registry


def test_discover_modules_returns_all_builtin() -> None:
    specs = discover_modules()
    names = sorted(s.name for s in specs)
    assert "audio_normalize" in names
    assert "file_write" in names
    assert "llm_prompt" in names
    assert "llm_summarize" in names
    assert "source_fetch" in names
    assert "webpage_fetch" in names
    assert "whisper_transcribe" in names
    # New modules (Phase 3)
    assert "rss_feed" in names
    assert "folder_watch" in names
    assert "parse_pdf" in names
    assert "webhook" in names
    assert "local_db" in names
    assert "llm_classify" in names
    assert "llm_extract" in names
    assert "embeddings" in names
    # New modules (Phase 9)
    assert "text_split" in names
    assert "ocr" in names
    assert "text_clean" in names
    assert "metadata_extract" in names
    assert "vector_store" in names
    assert "email_send" in names
    assert "obsidian_vault" in names
    assert "slack_notify" in names
    assert "email_inbox" in names
    assert "youtube_playlist" in names
    assert "s3_watcher" in names
    assert "llm_sentiment" in names
    # Phase 13
    assert "vinsium_node" in names


def test_discovered_modules_are_modulespec() -> None:
    for spec in discover_modules():
        assert isinstance(spec, ModuleSpec)


def test_step_type_auto_derived() -> None:
    specs = {s.name: s for s in discover_modules()}
    assert specs["source_fetch"].step_type == "input.source_fetch"
    assert specs["webpage_fetch"].step_type == "input.webpage_fetch"
    assert specs["audio_normalize"].step_type == "transform.audio_normalize"
    assert specs["whisper_transcribe"].step_type == "ai.whisper_transcribe"
    assert specs["llm_summarize"].step_type == "ai.llm_summarize"
    assert specs["file_write"].step_type == "output.file_write"


def test_aliases_present() -> None:
    specs = {s.name: s for s in discover_modules()}
    assert "source.fetch" in specs["source_fetch"].aliases
    assert "audio.normalize" in specs["audio_normalize"].aliases
    assert "whisper.transcribe" in specs["whisper_transcribe"].aliases
    assert "llm.summarize" in specs["llm_summarize"].aliases


def test_handlers_are_callable() -> None:
    for spec in discover_modules():
        assert callable(spec.handler)


def test_categories_match_directories() -> None:
    for spec in discover_modules():
        assert spec.category in ("input", "transform", "ai", "output", "meta")


def test_global_registry_has_new_step_types() -> None:
    for step_type in [
        "input.source_fetch",
        "input.webpage_fetch",
        "transform.audio_normalize",
        "ai.whisper_transcribe",
        "ai.llm_summarize",
        "ai.llm_prompt",
        "output.file_write",
    ]:
        handler = global_registry.get(step_type)
        assert callable(handler)


def test_global_registry_has_legacy_aliases() -> None:
    for alias in ["source.fetch", "audio.normalize", "whisper.transcribe", "llm.summarize", "llm.prompt"]:
        handler = global_registry.get(alias)
        assert callable(handler)


def test_new_and_alias_types_resolve_to_same_handler() -> None:
    pairs = [
        ("input.source_fetch", "source.fetch"),
        ("transform.audio_normalize", "audio.normalize"),
        ("ai.whisper_transcribe", "whisper.transcribe"),
        ("ai.llm_summarize", "llm.summarize"),
        ("ai.llm_prompt", "llm.prompt"),
    ]
    for new_type, alias in pairs:
        assert global_registry.get(new_type) is global_registry.get(alias)


def test_modulespec_defaults() -> None:
    def _dummy(ctx, step):
        return ctx

    spec = ModuleSpec(
        name="test_mod",
        version="1.0.0",
        category="input",
        description="A test module",
        handler=_dummy,
    )
    assert spec.step_type == "input.test_mod"
    assert spec.aliases == ()
    assert spec.dependencies == ()
    assert spec.config_schema == ()
    assert spec.reads == ()
    assert spec.writes == ()
    assert spec.safety == "safe"


def test_webpage_fetch_spec_properties() -> None:
    specs = {s.name: s for s in discover_modules()}
    wf = specs["webpage_fetch"]
    assert wf.category == "input"
    assert wf.step_type == "input.webpage_fetch"
    assert wf.aliases == ()
    assert any(w.key == "webpage_text" for w in wf.writes)
    assert any(w.key == "display_name" for w in wf.writes)


def test_file_write_spec_properties() -> None:
    specs = {s.name: s for s in discover_modules()}
    fw = specs["file_write"]
    assert fw.category == "output"
    assert fw.step_type == "output.file_write"
    assert fw.aliases == ()
    assert any(c.name == "input_key" for c in fw.config_schema)
    assert any(w.key == "export_output_path" for w in fw.writes)


def test_llm_summarize_has_input_key_config() -> None:
    specs = {s.name: s for s in discover_modules()}
    ls = specs["llm_summarize"]
    assert any(c.name == "input_key" for c in ls.config_schema)


def test_llm_prompt_spec_properties() -> None:
    specs = {s.name: s for s in discover_modules()}
    lp = specs["llm_prompt"]
    assert lp.category == "ai"
    assert lp.step_type == "ai.llm_prompt"
    assert "llm.prompt" in lp.aliases
    assert any(c.name == "prompt_template" for c in lp.config_schema)
    assert any(c.name == "input_key" for c in lp.config_schema)
    assert any(c.name == "output_key" for c in lp.config_schema)
    assert any(r.key == "input_text" for r in lp.reads)
    assert any(w.key == "llm_output" for w in lp.writes)
    assert any(w.key == "output_text" for w in lp.writes)


def test_modulespec_explicit_step_type() -> None:
    def _dummy(ctx, step):
        return ctx

    spec = ModuleSpec(
        name="test_mod",
        version="1.0.0",
        category="input",
        description="A test module",
        handler=_dummy,
        step_type="custom.type",
    )
    assert spec.step_type == "custom.type"


def test_modulespec_invalid_safety_raises() -> None:
    def _dummy(ctx, step):
        return ctx

    try:
        ModuleSpec(
            name="bad_safety",
            version="1.0.0",
            category="input",
            description="A test module",
            handler=_dummy,
            safety="dangerous",
        )
    except ValueError as exc:
        assert "Invalid module safety value" in str(exc)
        return
    raise AssertionError("Expected ValueError for invalid ModuleSpec.safety")


def test_network_modules_are_tagged() -> None:
    specs = {s.name: s for s in discover_modules()}
    network_expected = {
        "rss_feed",
        "webpage_fetch",
        "source_fetch",
        "llm_summarize",
        "llm_prompt",
        "llm_classify",
        "llm_extract",
        "embeddings",
        "webhook",
        # Phase 9 network modules
        "email_send",
        "slack_notify",
        "email_inbox",
        "youtube_playlist",
        "s3_watcher",
        "llm_sentiment",
        "vinsium_node",
    }
    for name in network_expected:
        assert specs[name].network is True, f"{name} should have network=True"
    # Spot-check a non-network module
    assert specs["audio_normalize"].network is False


def test_trusted_only_modules_are_tagged() -> None:
    specs = {s.name: s for s in discover_modules()}
    assert specs["webhook"].safety == "trusted_only"
    assert specs["local_db"].safety == "trusted_only"
    # Phase 9 trusted_only modules
    assert specs["vector_store"].safety == "trusted_only"
    assert specs["email_send"].safety == "trusted_only"
    assert specs["obsidian_vault"].safety == "trusted_only"
    assert specs["slack_notify"].safety == "trusted_only"
    assert specs["email_inbox"].safety == "trusted_only"
    assert specs["s3_watcher"].safety == "trusted_only"
    assert specs["vinsium_node"].safety == "trusted_only"


def test_discovery_importable_from_clean_process() -> None:
    src_dir = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}:{existing}" if existing else str(src_dir)
    proc = subprocess.run(
        [sys.executable, "-c", "import solus.modules.discovery"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout

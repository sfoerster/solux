from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import requests

from .config import Config, effective_external_modules_dir
from .modules.spec import ModuleSpec
from .paths import ensure_dir
from .workflows.loader import WorkflowLoadError, list_workflows, load_workflow
from .workflows.models import Workflow
from .workflows.registry import StepRegistry, build_registry


def _print(status: str, message: str, hint: str | None = None) -> None:
    print(f"[{status}] {message}")
    if hint:
        print(f"      -> {hint}")


def _find_binary(binary: str) -> str | None:
    binary_path = Path(binary).expanduser()
    if "/" in binary or binary_path.is_absolute():
        if binary_path.exists() and binary_path.is_file():
            return str(binary_path)
        return None
    return shutil.which(binary)


def _looks_like_pyenv_not_found(message: str, tool_name: str) -> bool:
    normalized = message.lower()
    return "pyenv:" in normalized and f"{tool_name}: command not found" in normalized


def _check_binary_runs(binary: str, version_flag: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [binary, version_flag],
            capture_output=True,
            text=True,
            check=False,
            timeout=4,
        )
    except FileNotFoundError:
        return False, "binary not found at runtime"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)

    if proc.returncode == 0:
        return True, ""
    message = proc.stderr.strip() or proc.stdout.strip() or "exited with non-zero status"
    return False, message


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _ytdlp_install_hint() -> str:
    if _is_macos():
        return "Install: brew install yt-dlp  OR  pip install yt-dlp"
    return "Install: pip install yt-dlp  (or use your distro package manager)"


def _ffmpeg_install_hint() -> str:
    if _is_macos():
        return "Install: brew install ffmpeg"
    if _is_linux():
        return "Install: sudo apt install ffmpeg  (Debian/Ubuntu) or equivalent for your distro"
    return "Install ffmpeg from https://ffmpeg.org/download.html"


def _whisper_install_hint() -> str:
    return (
        "Build whisper.cpp:\n"
        "      git clone https://github.com/ggml-org/whisper.cpp && cd whisper.cpp\n"
        "      cmake -B build && cmake --build build --config Release\n"
        "      Then download a model: bash ./models/download-ggml-model.sh base\n"
        "      Set whisper.cli_path and whisper.model_path in config.toml"
    )


def _ollama_install_hint() -> str:
    if _is_macos():
        return "Install: brew install ollama  OR  curl -fsSL https://ollama.ai/install.sh | sh"
    if _is_linux():
        return "Install: curl -fsSL https://ollama.ai/install.sh | sh"
    return "Install Ollama from https://ollama.ai and verify [ollama].base_url in config.toml"


def _check_yt_dlp(config: Config) -> bool:
    yt_dlp_path = _find_binary(config.yt_dlp.binary)
    if yt_dlp_path:
        runnable, message = _check_binary_runs(yt_dlp_path, "--version")
        if runnable:
            _print("OK", f"yt-dlp found at {yt_dlp_path}")
            return False
        hint = "Set [yt_dlp].binary to a direct executable path."
        if _looks_like_pyenv_not_found(message, "yt-dlp"):
            hint = (
                "pyenv shim is selected but no active version provides yt-dlp. "
                "Set [yt_dlp].binary to ~/.pyenv/versions/<env>/bin/yt-dlp "
                "or activate the matching pyenv version."
            )
        _print("WARN", f"yt-dlp is present but not runnable: {message}", hint)
        return True

    _print(
        "WARN",
        f"yt-dlp binary not found: {config.yt_dlp.binary}",
        _ytdlp_install_hint(),
    )
    return True


def _check_ffmpeg(config: Config) -> bool:
    ffmpeg_path = _find_binary(config.ffmpeg.binary)
    if ffmpeg_path:
        runnable, message = _check_binary_runs(ffmpeg_path, "-version")
        if runnable:
            _print("OK", f"ffmpeg found at {ffmpeg_path}")
            return False
        _print(
            "WARN",
            f"ffmpeg is present but not runnable: {message}",
            "Set [ffmpeg].binary to a valid executable path.",
        )
        return True

    _print(
        "WARN",
        f"ffmpeg binary not found: {config.ffmpeg.binary}",
        _ffmpeg_install_hint(),
    )
    return True


def _check_whisper(config: Config) -> bool:
    missing_required = False
    if config.whisper.cli_path and config.whisper.cli_path.exists():
        _print("OK", f"whisper-cli found at {config.whisper.cli_path}")
    else:
        missing_required = True
        missing = config.whisper.cli_path or "<not configured>"
        _print(
            "WARN",
            f"whisper-cli not found at {missing}",
            _whisper_install_hint(),
        )

    if config.whisper.model_path and config.whisper.model_path.exists():
        _print("OK", f"whisper model found at {config.whisper.model_path}")
    else:
        missing_required = True
        missing = config.whisper.model_path or "<not configured>"
        _print(
            "WARN",
            f"whisper model file not found at {missing}",
            "Download a GGML model and set 'whisper.model_path' in config.toml",
        )
    return missing_required


def _check_ollama(config: Config) -> bool:
    tags_url = f"{config.ollama.base_url}/api/tags"
    try:
        response = requests.get(tags_url, timeout=5)
        response.raise_for_status()
        _print("OK", f"Ollama reachable at {config.ollama.base_url}")
        payload = response.json()
        available_models = {item.get("name") for item in payload.get("models", [])}
        if config.ollama.model in available_models:
            _print("OK", f"Ollama model '{config.ollama.model}' available")
            return False
        _print(
            "WARN",
            f"Ollama model '{config.ollama.model}' not found",
            f"Run: ollama pull {config.ollama.model}",
        )
        return True
    except requests.RequestException as exc:
        _print(
            "WARN",
            f"Ollama not reachable at {config.ollama.base_url}: {exc}",
            _ollama_install_hint(),
        )
        return True
    except ValueError:
        _print(
            "WARN",
            f"Ollama returned unexpected response from {tags_url}",
            "Check if Ollama is healthy and responds with JSON.",
        )
        return True


def _collect_workflow_specs(
    workflow: Workflow,
    *,
    workflow_dir: Path,
    registry: StepRegistry,
    seen_workflows: set[str] | None = None,
) -> tuple[dict[str, ModuleSpec], list[str]]:
    seen = seen_workflows if seen_workflows is not None else set()
    if workflow.name in seen:
        return {}, []
    seen.add(workflow.name)

    collected: dict[str, ModuleSpec] = {}
    issues: list[str] = []

    for step in workflow.steps:
        if step.type == "workflow":
            sub_name = str(step.config.get("name", "")).strip()
            if not sub_name:
                issues.append(f"Workflow '{workflow.name}' step '{step.name}' is missing required config.name")
                continue
            try:
                sub_workflow = load_workflow(
                    sub_name,
                    workflow_dir=workflow_dir,
                    strict_secrets=False,
                    warn_missing_secrets=False,
                )
            except WorkflowLoadError as exc:
                issues.append(f"Workflow '{workflow.name}' step '{step.name}': {exc}")
                continue
            nested_specs, nested_issues = _collect_workflow_specs(
                sub_workflow,
                workflow_dir=workflow_dir,
                registry=registry,
                seen_workflows=seen,
            )
            collected.update(nested_specs)
            issues.extend(nested_issues)
            continue

        spec = registry.get_spec(step.type)
        if spec is None:
            issues.append(f"Workflow '{workflow.name}' step '{step.name}' uses unknown module type '{step.type}'")
            continue
        collected[spec.step_type] = spec

    return collected, issues


def run_doctor(config: Config, workflow_name: str | None = None) -> int:
    missing_required = False

    if config.config_exists:
        _print("OK", f"Config file loaded from {config.config_path}")
    else:
        _print(
            "WARN",
            f"Config file not found at {config.config_path}; using defaults where possible",
            "Create config.toml to set whisper paths and preferred model.",
        )

    cache_dir = ensure_dir(config.paths.cache_dir)
    _print("OK", f"Cache dir: {cache_dir}")

    workflows_dir = ensure_dir(config.workflows_dir)
    _print("OK", f"Workflow directory: {workflows_dir}")
    workflows, invalid = list_workflows(
        workflow_dir=workflows_dir,
        interpolate_secrets=False,
        warn_missing_secrets=False,
    )
    _print("OK", f"Discovered workflows: {len(workflows)}")
    if invalid:
        missing_required = True
        _print("WARN", f"Invalid workflow definitions: {len(invalid)}")
        for item in invalid[:5]:
            _print("WARN", item)

    external_dir = effective_external_modules_dir(config)
    if external_dir is None:
        _print("OK", "External modules are disabled in untrusted mode.")

    target_workflow = workflow_name.strip() if workflow_name else ""
    if not target_workflow:
        missing_required |= _check_yt_dlp(config)
        missing_required |= _check_ffmpeg(config)
        missing_required |= _check_whisper(config)
        missing_required |= _check_ollama(config)

        missing_required_ref = [missing_required]
        _check_module_dependencies(
            missing_required_ref=missing_required_ref,
            external_dir=external_dir,
        )
        return 1 if missing_required_ref[0] else 0

    _print("OK", f"Doctor scope: workflow '{target_workflow}'")
    try:
        workflow = load_workflow(
            target_workflow,
            workflow_dir=workflows_dir,
            strict_secrets=False,
            warn_missing_secrets=False,
        )
    except WorkflowLoadError as exc:
        _print("WARN", str(exc))
        return 1

    registry = build_registry(external_dir=external_dir)
    workflow_specs, workflow_issues = _collect_workflow_specs(
        workflow,
        workflow_dir=workflows_dir,
        registry=registry,
    )
    _print("OK", f"Workflow modules checked: {len(workflow_specs)}")
    if workflow_issues:
        missing_required = True
        for item in workflow_issues[:10]:
            _print("WARN", item)

    dep_names: set[str] = set()
    for spec in workflow_specs.values():
        for dep in spec.dependencies:
            dep_names.add(dep.name)

    if "yt-dlp" in dep_names:
        missing_required |= _check_yt_dlp(config)
    if "ffmpeg" in dep_names:
        missing_required |= _check_ffmpeg(config)
    if "whisper-cli" in dep_names:
        missing_required |= _check_whisper(config)
    if "ollama" in dep_names:
        missing_required |= _check_ollama(config)

    missing_required_ref = [missing_required]
    _check_module_dependencies(
        missing_required_ref=missing_required_ref,
        external_dir=external_dir,
        specs=list(workflow_specs.values()),
        skip_binary_deps={"yt-dlp", "ffmpeg", "whisper-cli"},
    )
    return 1 if missing_required_ref[0] else 0


def _check_module_dependencies(
    missing_required_ref: list[bool],
    external_dir: Path | None = None,
    specs: list[ModuleSpec] | None = None,
    skip_binary_deps: set[str] | None = None,
) -> None:
    from .modules.discovery import discover_modules

    active_specs = specs if specs is not None else discover_modules(external_dir=external_dir)
    skip_binary_deps = skip_binary_deps or set()
    if specs is None:
        _print("OK", f"Discovered modules: {len(active_specs)}")
    for spec in active_specs:
        for dep in spec.dependencies:
            if dep.kind != "binary" or dep.name in skip_binary_deps:
                continue
            found = _find_binary(dep.name)
            if found:
                runnable = True
                if dep.check_cmd:
                    runnable, _ = _check_binary_runs(
                        dep.check_cmd[0], dep.check_cmd[1] if len(dep.check_cmd) > 1 else "--version"
                    )
                if runnable:
                    _print("OK", f"Module {spec.name}: {dep.name} available")
                else:
                    missing_required_ref[0] = True
                    _print("WARN", f"Module {spec.name}: {dep.name} found but not runnable", dep.hint or None)
            else:
                missing_required_ref[0] = True
                _print("WARN", f"Module {spec.name}: {dep.name} not found", dep.hint or None)

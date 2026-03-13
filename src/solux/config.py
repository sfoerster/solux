from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
import tomllib

DEFAULT_OIDC_ALLOWED_ALGS: tuple[str, ...] = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
)
DEFAULT_UI_WORKFLOW = "webpage_summary"
_WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class ConfigError(Exception):
    """Raised when config parsing fails."""


@dataclass(frozen=True)
class PathsConfig:
    cache_dir: Path


@dataclass(frozen=True)
class WhisperConfig:
    cli_path: Path | None
    model_path: Path | None
    threads: int
    language: str | None = None
    temperature: float = 0.2
    entropy_thold: float = 2.8
    logprob_thold: float = -1.0


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str
    max_transcript_chars: int


@dataclass(frozen=True)
class BinaryConfig:
    binary: str


@dataclass(frozen=True)
class PromptsConfig:
    system: str | None = None
    tldr: str | None = None
    outline: str | None = None
    notes: str | None = None
    full: str | None = None


@dataclass(frozen=True)
class SecurityConfig:
    mode: str = "trusted"  # "trusted" | "untrusted"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_require_auth: bool = False
    oidc_allowed_algs: tuple[str, ...] = field(default_factory=lambda: DEFAULT_OIDC_ALLOWED_ALGS)
    strict_env_vars: bool = False  # Raise on missing ${env:VAR} instead of empty string
    webhook_secret: str = ""  # HMAC-SHA256 secret for webhook signature validation
    webhook_rate_limit: int = 60  # Max webhook requests per minute per source IP
    audit_db_key: str = ""  # SQLCipher encryption key for audit DB (empty = plain SQLite)


@dataclass(frozen=True)
class AuditConfig:
    enabled: bool = True
    syslog_addr: str = ""
    retention_days: int = 90
    hmac_key: str = ""  # HMAC-SHA256 key for signed audit log chain (empty = no signing)


@dataclass(frozen=True)
class UIConfig:
    default_workflow: str = DEFAULT_UI_WORKFLOW


@dataclass(frozen=True)
class Config:
    paths: PathsConfig
    whisper: WhisperConfig
    ollama: OllamaConfig
    yt_dlp: BinaryConfig
    ffmpeg: BinaryConfig
    prompts: PromptsConfig
    config_path: Path
    config_exists: bool
    security: SecurityConfig = field(default_factory=SecurityConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    workflows_dir: Path = Path("~/.config/solux/workflows.d").expanduser().resolve()
    modules_dir: Path = Path("~/.config/solux/modules.d").expanduser().resolve()
    triggers_dir: Path = Path("~/.config/solux/triggers.d").expanduser().resolve()


DEFAULT_CONFIG_PATH = Path("~/.config/solux/config.toml")
DEFAULT_CACHE_DIR = "~/.local/share/solux"
DEFAULT_WORKFLOWS_DIR = Path("~/.config/solux/workflows.d")
DEFAULT_MODULES_DIR = Path("~/.config/solux/modules.d")
DEFAULT_TRIGGERS_DIR = Path("~/.config/solux/triggers.d")
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"


def _expand_path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(os.path.expanduser(value)).resolve()


def _env_str(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _env_bool(name: str) -> bool | None:
    value = _env_str(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Invalid boolean environment value for {name}: {value!r}")


def _default_cache_dir() -> str:
    return _env_str("SOLUX_CACHE_DIR") or DEFAULT_CACHE_DIR


def _default_ollama_base_url() -> str:
    return _env_str("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL


def get_default_config_path() -> Path:
    return DEFAULT_CONFIG_PATH.expanduser().resolve()


def get_default_workflows_dir() -> Path:
    return DEFAULT_WORKFLOWS_DIR.expanduser().resolve()


def get_default_modules_dir() -> Path:
    return DEFAULT_MODULES_DIR.expanduser().resolve()


def get_default_triggers_dir() -> Path:
    return DEFAULT_TRIGGERS_DIR.expanduser().resolve()


def _shrink_home(path_str: str) -> str:
    home = str(Path.home())
    if path_str.startswith(home + "/"):
        return "~" + path_str[len(home) :]
    if path_str == home:
        return "~"
    return path_str


def _discover_binary(binary_name: str) -> str | None:
    path = shutil.which(binary_name)
    if not path:
        return None
    if "/.pyenv/shims/" in path:
        direct = _discover_pyenv_binary(binary_name)
        if direct:
            return direct
    return path


def _discover_pyenv_binary(binary_name: str) -> str | None:
    # Prefer pyenv's currently resolved tool path when available.
    try:
        proc = subprocess.run(
            ["pyenv", "which", binary_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        proc = None

    if proc and proc.returncode == 0:
        candidate = Path(proc.stdout.strip()).expanduser()
        if candidate.exists() and candidate.is_file() and "/.pyenv/shims/" not in str(candidate):
            return str(candidate.resolve())

    pyenv_root = Path(os.environ.get("PYENV_ROOT", "~/.pyenv")).expanduser()
    versions_dir = pyenv_root / "versions"
    if not versions_dir.exists():
        return None

    candidates = sorted(versions_dir.glob(f"**/bin/{binary_name}"))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
    return None


def _discover_whisper_cli() -> str | None:
    from_path = _discover_binary("whisper-cli")
    if from_path:
        return from_path

    candidates = [
        Path("~/src/whisper.cpp/build/bin/whisper-cli").expanduser(),
        Path("~/whisper.cpp/build/bin/whisper-cli").expanduser(),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
    return None


def _discover_whisper_model() -> str | None:
    search_dirs = [
        Path("~/src/whisper.cpp/models").expanduser(),
        Path("~/whisper.cpp/models").expanduser(),
    ]
    preferred = [
        "ggml-medium.bin",
        "ggml-base.bin",
        "ggml-small.bin",
        "ggml-large-v3.bin",
        "ggml-large.bin",
    ]

    for model_dir in search_dirs:
        if not model_dir.exists():
            continue
        for file_name in preferred:
            candidate = model_dir / file_name
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
        other = sorted(model_dir.glob("ggml-*.bin"))
        if other:
            return str(other[0].resolve())
    return None


def _discover_ollama_model(base_url: str) -> str:
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    try:
        response = requests.get(tags_url, timeout=2)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return DEFAULT_OLLAMA_MODEL

    names = [item.get("name") for item in payload.get("models", []) if isinstance(item, dict)]
    if DEFAULT_OLLAMA_MODEL in names:
        return DEFAULT_OLLAMA_MODEL
    if names:
        return str(names[0])
    return DEFAULT_OLLAMA_MODEL


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_bootstrap_config_toml() -> str:
    yt_dlp_bin = _discover_binary("yt-dlp") or "yt-dlp"
    ffmpeg_bin = _discover_binary("ffmpeg") or "ffmpeg"
    whisper_cli = _discover_whisper_cli() or ""
    whisper_model = _discover_whisper_model() or ""
    default_cache_dir = _default_cache_dir()
    default_ollama_base_url = _default_ollama_base_url()
    ollama_model = _discover_ollama_model(default_ollama_base_url)
    threads_default = os.cpu_count() or 4

    lines = [
        "# Auto-generated by `solux config`.",
        "# Review and adjust paths for your system.",
        "",
        "[paths]",
        f'cache_dir = "{_toml_escape(default_cache_dir)}"',
        "",
        "[whisper]",
        f'cli_path = "{_toml_escape(_shrink_home(whisper_cli))}"',
        f'model_path = "{_toml_escape(_shrink_home(whisper_model))}"',
        f"threads = {threads_default}",
        '# language = "en"                      # Force language (default: auto-detect)',
        "# temperature = 0.2                    # Sampling temperature (lower = less repetition)",
        "# entropy_thold = 2.8                  # Entropy threshold for repetition detection",
        "# logprob_thold = -1.0                 # Log-probability threshold for segment filtering",
        "",
        "[ollama]",
        f'base_url = "{_toml_escape(default_ollama_base_url)}"',
        f'model = "{_toml_escape(ollama_model)}"',
        "",
        "[yt_dlp]",
        f'binary = "{_toml_escape(yt_dlp_bin)}"',
        "",
        "[ffmpeg]",
        f'binary = "{_toml_escape(ffmpeg_bin)}"',
        "",
        "[workflows]",
        f'dir = "{_toml_escape(_shrink_home(str(get_default_workflows_dir())))}"',
        "",
        "[modules]",
        f'dir = "{_toml_escape(_shrink_home(str(get_default_modules_dir())))}"',
        "",
        "[triggers]",
        f'dir = "{_toml_escape(_shrink_home(str(get_default_triggers_dir())))}"',
        "",
        "[security]",
        'mode = "trusted"',
        '# webhook_secret = ""  # HMAC-SHA256 secret for webhook signature validation',
        '# oidc_allowed_algs = ["RS256", "ES256", "PS256"]',
        "",
        "[ui]",
        f'default_workflow = "{DEFAULT_UI_WORKFLOW}"',
        "",
    ]
    return "\n".join(lines)


def ensure_config_file(config_path: str | Path | None = None) -> tuple[Path, bool]:
    path = Path(config_path).expanduser().resolve() if config_path else get_default_config_path()
    if path.exists():
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_bootstrap_config_toml(), encoding="utf-8")
    return path, True


def load_config(config_path: str | Path | None = None) -> Config:
    path = Path(config_path).expanduser().resolve() if config_path else get_default_config_path()
    data: dict[str, Any] = {}
    config_exists = path.exists()

    if config_exists:
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Failed to parse config at {path}: {exc}") from exc

    paths_data = data.get("paths", {})
    whisper_data = data.get("whisper", {})
    ollama_data = data.get("ollama", {})
    yt_dlp_data = data.get("yt_dlp", {})
    ffmpeg_data = data.get("ffmpeg", {})
    prompts_data = data.get("prompts", {})
    workflows_data = data.get("workflows", {})
    modules_data = data.get("modules", {})
    triggers_data = data.get("triggers", {})
    security_data = data.get("security", {})
    audit_data = data.get("audit", {})
    ui_data = data.get("ui", {})

    cache_dir_raw = paths_data.get("cache_dir")
    cache_dir = _expand_path(cache_dir_raw or _default_cache_dir())
    if cache_dir is None:
        raise ConfigError("Invalid cache_dir in config")

    workflows_dir = _expand_path(workflows_data.get("dir") or str(get_default_workflows_dir()))
    if workflows_dir is None:
        raise ConfigError("Invalid workflows.dir in config")

    modules_dir = _expand_path(modules_data.get("dir") or str(get_default_modules_dir()))
    if modules_dir is None:
        raise ConfigError("Invalid modules.dir in config")

    triggers_dir = _expand_path(triggers_data.get("dir") or str(get_default_triggers_dir()))
    if triggers_dir is None:
        raise ConfigError("Invalid triggers.dir in config")

    threads_default = os.cpu_count() or 4
    threads = whisper_data.get("threads", threads_default)
    try:
        threads_int = max(1, int(threads))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid whisper.threads value: {threads!r}") from exc

    max_transcript_chars_raw = ollama_data.get("max_transcript_chars", 0)
    try:
        max_transcript_chars = max(0, int(max_transcript_chars_raw))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid ollama.max_transcript_chars value: {max_transcript_chars_raw!r}") from exc

    def _opt_str(d: dict, key: str) -> str | None:
        v = d.get(key)
        return str(v) if v is not None else None

    security_mode = (_env_str("SOLUX_SECURITY_MODE") or str(security_data.get("mode", "trusted"))).strip().lower()
    if security_mode not in {"trusted", "untrusted"}:
        raise ConfigError(f"Invalid security.mode value: {security_mode!r}. Expected 'trusted' or 'untrusted'.")
    oidc_issuer = (_env_str("SOLUX_OIDC_ISSUER") or str(security_data.get("oidc_issuer", ""))).strip()
    oidc_audience = (_env_str("SOLUX_OIDC_AUDIENCE") or str(security_data.get("oidc_audience", ""))).strip()
    oidc_require_auth_env = _env_bool("SOLUX_OIDC_REQUIRE_AUTH")
    oidc_require_auth = (
        oidc_require_auth_env
        if oidc_require_auth_env is not None
        else bool(security_data.get("oidc_require_auth", False))
    )
    strict_env_vars = bool(security_data.get("strict_env_vars", False))
    webhook_secret = (_env_str("SOLUX_WEBHOOK_SECRET") or str(security_data.get("webhook_secret", ""))).strip()
    webhook_rate_limit_raw = _env_str("SOLUX_WEBHOOK_RATE_LIMIT") or security_data.get("webhook_rate_limit", 60)
    try:
        webhook_rate_limit = int(webhook_rate_limit_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"Invalid security.webhook_rate_limit value: {webhook_rate_limit_raw!r}. Expected an integer >= 1."
        ) from exc
    if webhook_rate_limit < 1:
        raise ConfigError(
            f"Invalid security.webhook_rate_limit value: {webhook_rate_limit!r}. Expected an integer >= 1."
        )
    if oidc_require_auth and not oidc_audience:
        raise ConfigError("Invalid security config: oidc_audience must be set when oidc_require_auth=true.")
    oidc_allowed_algs_raw = security_data.get("oidc_allowed_algs", None)
    if oidc_allowed_algs_raw is None:
        oidc_allowed_algs = DEFAULT_OIDC_ALLOWED_ALGS
    elif isinstance(oidc_allowed_algs_raw, (list, tuple)):
        cleaned_algs: list[str] = []
        for idx, item in enumerate(oidc_allowed_algs_raw):
            if not isinstance(item, str) or not item.strip():
                raise ConfigError(
                    f"Invalid security.oidc_allowed_algs[{idx}] value: {item!r}. Expected a non-empty algorithm string."
                )
            cleaned_algs.append(item.strip())
        if not cleaned_algs:
            raise ConfigError("Invalid security.oidc_allowed_algs value: list must not be empty.")
        oidc_allowed_algs = tuple(cleaned_algs)
    else:
        raise ConfigError("Invalid security.oidc_allowed_algs value: expected a list of JWT algorithm names.")

    default_workflow = str(ui_data.get("default_workflow", DEFAULT_UI_WORKFLOW)).strip()
    if not default_workflow:
        default_workflow = DEFAULT_UI_WORKFLOW
    if not _WORKFLOW_NAME_RE.fullmatch(default_workflow):
        raise ConfigError(
            f"Invalid ui.default_workflow value: {default_workflow!r}. "
            "Use only letters, digits, underscore, and hyphen."
        )

    audit_enabled_env = _env_bool("SOLUX_AUDIT_ENABLED")
    audit_enabled = audit_enabled_env if audit_enabled_env is not None else bool(audit_data.get("enabled", True))
    audit_syslog_addr = (
        _env_str("SOLUX_AUDIT_SYSLOG_ADDR") or _env_str("AUDIT_SYSLOG_ADDR") or str(audit_data.get("syslog_addr", ""))
    ).strip()
    audit_retention_raw = audit_data.get("retention_days", 90)
    try:
        audit_retention_days = max(1, int(audit_retention_raw))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid audit.retention_days value: {audit_retention_raw!r}") from exc

    return Config(
        paths=PathsConfig(cache_dir=cache_dir),
        whisper=WhisperConfig(
            cli_path=_expand_path(whisper_data.get("cli_path")),
            model_path=_expand_path(whisper_data.get("model_path")),
            threads=threads_int,
            language=_opt_str(whisper_data, "language"),
            temperature=float(whisper_data.get("temperature", 0.2)),
            entropy_thold=float(whisper_data.get("entropy_thold", 2.8)),
            logprob_thold=float(whisper_data.get("logprob_thold", -1.0)),
        ),
        ollama=OllamaConfig(
            base_url=str(ollama_data.get("base_url", _default_ollama_base_url())).rstrip("/"),
            model=str(ollama_data.get("model", DEFAULT_OLLAMA_MODEL)),
            max_transcript_chars=max_transcript_chars,
        ),
        yt_dlp=BinaryConfig(binary=str(yt_dlp_data.get("binary", "yt-dlp"))),
        ffmpeg=BinaryConfig(binary=str(ffmpeg_data.get("binary", "ffmpeg"))),
        prompts=PromptsConfig(
            system=_opt_str(prompts_data, "system"),
            tldr=_opt_str(prompts_data, "tldr"),
            outline=_opt_str(prompts_data, "outline"),
            notes=_opt_str(prompts_data, "notes"),
            full=_opt_str(prompts_data, "full"),
        ),
        security=SecurityConfig(
            mode=security_mode,
            oidc_issuer=oidc_issuer,
            oidc_audience=oidc_audience,
            oidc_require_auth=oidc_require_auth,
            oidc_allowed_algs=oidc_allowed_algs,
            strict_env_vars=strict_env_vars,
            webhook_secret=webhook_secret,
            webhook_rate_limit=webhook_rate_limit,
        ),
        audit=AuditConfig(
            enabled=audit_enabled,
            syslog_addr=audit_syslog_addr,
            retention_days=audit_retention_days,
        ),
        ui=UIConfig(default_workflow=default_workflow),
        config_path=path,
        config_exists=config_exists,
        workflows_dir=workflows_dir,
        modules_dir=modules_dir,
        triggers_dir=triggers_dir,
    )


def external_modules_enabled(config: Config | None) -> bool:
    """Return True when external modules are allowed by security policy."""
    if config is None:
        return False
    mode = str(getattr(getattr(config, "security", None), "mode", "trusted")).strip().lower()
    return mode != "untrusted"


def effective_external_modules_dir(config: Config | None) -> Path | None:
    """Return modules_dir if enabled for current security mode; otherwise None."""
    if not external_modules_enabled(config):
        return None
    modules_dir = getattr(config, "modules_dir", None) if config is not None else None
    return modules_dir if isinstance(modules_dir, Path) else None


def default_workflow_name(config: Config | None) -> str:
    if config is None:
        return DEFAULT_UI_WORKFLOW
    candidate = str(getattr(getattr(config, "ui", None), "default_workflow", DEFAULT_UI_WORKFLOW)).strip()
    if candidate and _WORKFLOW_NAME_RE.fullmatch(candidate):
        return candidate
    return DEFAULT_UI_WORKFLOW

"""``solux init`` — guided first-run setup."""

from __future__ import annotations

import argparse
import sys

import requests

from ..config import ConfigError, ensure_config_file, load_config
from ..doctor import run_doctor
from .fmt import bold, dim, green, red, yellow

_MY_SUMMARIZER_YAML = """\
name: my_summarizer
description: "Fetch a webpage, clean the text, and summarize it with a local LLM."
steps:
  - name: fetch_webpage
    type: input.webpage_fetch

  - name: clean_text
    type: transform.text_clean
    config:
      input_key: webpage_text
      output_key: cleaned_text

  - name: summarize
    type: ai.llm_summarize
    config:
      input_key: cleaned_text

  - name: write_output
    type: output.file_write
"""


def _check_ollama_reachable(base_url: str, model: str) -> None:
    """Print Ollama status and actionable install/pull hints."""
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    try:
        resp = requests.get(tags_url, timeout=3)
        resp.raise_for_status()
        print(f"{green('[OK]')} Ollama reachable at {base_url}")
        payload = resp.json()
        available = {item.get("name") for item in payload.get("models", []) if isinstance(item, dict)}
        if model in available:
            print(f"{green('[OK]')} Model '{model}' available")
        else:
            print(f"{yellow('[!!]')} Model '{model}' not found locally")
            print(f"      Run: {bold(f'ollama pull {model}')}")
    except requests.RequestException:
        print(f"{red('[!!]')} Ollama not reachable at {base_url}")
        print()
        if sys.platform == "darwin":
            print(f"  Install Ollama:  {bold('brew install ollama')}")
        elif sys.platform.startswith("linux"):
            print(f"  Install Ollama:  {bold('curl -fsSL https://ollama.ai/install.sh | sh')}")
        else:
            print(f"  Install Ollama:  {bold('https://ollama.ai')}")
        print(f"  Start server:    {bold('ollama serve')}")
        print()


def cmd_init(args: argparse.Namespace | None = None) -> int:
    del args  # unused

    # 1. Ensure config file exists (idempotent)
    try:
        config_path, created = ensure_config_file()
    except OSError as exc:
        print(f"Failed to create config: {exc}", file=sys.stderr)
        return 1

    if created:
        print(f"{green('[OK]')} Created config: {config_path}")
    else:
        print(f"{green('[OK]')} Config already exists: {config_path}")

    # 2. Load config
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    # 3. Check Ollama
    print()
    _check_ollama_reachable(config.ollama.base_url, config.ollama.model)

    # 4. Scaffold my_summarizer.yaml
    workflows_dir = config.workflows_dir
    workflows_dir.mkdir(parents=True, exist_ok=True)
    scaffold_path = workflows_dir / "my_summarizer.yaml"
    if scaffold_path.exists():
        print(f"{dim('[OK]')} Workflow already exists: {scaffold_path}")
    else:
        scaffold_path.write_text(_MY_SUMMARIZER_YAML, encoding="utf-8")
        print(f"{green('[OK]')} Scaffolded workflow: {scaffold_path}")

    # 5. Run doctor scoped to webpage_summary
    print()
    run_doctor(config, workflow_name="webpage_summary")

    # 6. Next steps
    print()
    print(bold("Next steps:"))
    print(f"  1. Try it:  {bold('solux https://example.com/any-article')}")
    print(f"  2. Edit:    {dim(str(scaffold_path))}")
    print(f"  3. Explore: {bold('solux examples')}")
    print(f"  4. Audio:   {bold('solux doctor --workflow audio_summary')}")

    return 0

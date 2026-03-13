# Quick Start

Get from `git clone` to running a real workflow in under 60 seconds.

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) with any local model

That's it. No ffmpeg, no whisper, no yt-dlp needed for your first run.

## 1. Install

```bash
git clone https://github.com/sfoerster/solux.git
cd solux
pip install -e .
```

## 2. Set up

```bash
solux init
```

This single command:

- Creates `~/.config/solux/config.toml` with sensible defaults
- Checks that Ollama is running and your model is available
- Scaffolds a starter workflow (`my_summarizer.yaml`) in `~/.config/solux/workflows.d/`
- Runs a health check scoped to what you actually need

If Ollama isn't installed yet, `solux init` prints platform-specific install instructions.

### Pull a model (if needed)

```bash
ollama pull qwen3:8b
```

## 3. Run

```bash
solux https://example.com/any-article
```

Solux fetches the page, extracts text, summarizes it with your local LLM, and prints the result. The default workflow is `webpage_summary` — no audio stack required.

### Dry-run first

Preview what a workflow will do without executing it:

```bash
solux run --dry-run --workflow webpage_summary https://example.com
```

## 4. Explore

```bash
solux examples                # browse workflow templates
solux workflows list          # see all available workflows
solux modules list            # see all available modules
```

## 5. Edit your workflow

Open the scaffolded workflow and customize it:

```bash
$EDITOR ~/.config/solux/workflows.d/my_summarizer.yaml
```

The starter workflow chains four steps:

```yaml
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
```

Run it:

```bash
solux run --workflow my_summarizer https://example.com/article
```

## Health checks

```bash
solux doctor                                  # check deps for your workflows
solux doctor --workflow audio_summary         # check audio pipeline deps
solux doctor --all                            # check everything
solux doctor --fix                            # show copy-pasteable fix commands
```

By default, `solux doctor` only checks dependencies that your configured workflows actually use. Use `--all` to check everything (including audio tools you may not need yet).

## Next steps

- **Audio pipeline**: Install yt-dlp + ffmpeg + whisper.cpp, then run `solux doctor --workflow audio_summary`
- **Background processing**: `solux ingest URL && solux worker start`
- **Triggers**: `solux triggers examples` for RSS, cron, folder-watch, and email templates
- **Web UI**: `solux serve` starts a dashboard at http://localhost:8765
- **Full tutorial**: [docs/TUTORIAL.md](TUTORIAL.md)
- **Custom modules**: Drop a `.py` file in `~/.config/solux/modules.d/` — see [README.md](../README.md#external-modules)

# Solux Tutorial

Solux is a local-first AI workflow engine. It chains together input sources, text transforms, local LLM calls, and output destinations—entirely on your machine with no cloud API dependency. Workflows are composed in YAML, modules are extensible Python, and a background worker with a SQLite queue handles asynchronous processing.

---

## Table of Contents

1. [Installation](#installation)
2. [Quick Start](#quick-start)
3. [Core Concepts](#core-concepts)
4. [Configuration](#configuration)
5. [CLI Reference](#cli-reference)
6. [Workflow Authoring](#workflow-authoring)
7. [Module Reference](#module-reference)
8. [Background Worker & Queue](#background-worker--queue)
9. [Triggers](#triggers)
10. [Web UI](#web-ui)
11. [Security](#security)
12. [Writing Custom Modules](#writing-custom-modules)
13. [Secrets Management](#secrets-management)
14. [Advanced Patterns](#advanced-patterns)
15. [Deployment](#deployment)
16. [Troubleshooting](#troubleshooting)

---

## Installation

### Python package

```bash
pip install -e .
```

Optional extras:

```bash
pip install 'solux[pdf]'     # PDF text extraction (pypdf)
pip install 'solux[ocr]'     # Tesseract OCR (pytesseract)
pip install 'solux[s3]'      # S3/MinIO support (boto3)
pip install 'solux[vector]'  # ChromaDB vector store
pip install 'solux[oidc]'    # OIDC/JWT auth for the web UI
pip install -e '.[dev]'      # Development dependencies (pytest, ruff, mypy, pytest-cov)
```

### External dependencies

Solux delegates heavy lifting to external tools that must be installed separately:

| Tool | Purpose | Install |
|------|---------|---------|
| `yt-dlp` | Video/audio download | `pip install yt-dlp` or system package |
| `ffmpeg` | Audio normalization | System package (`apt`, `brew`, etc.) |
| `whisper-cli` | Transcription (whisper.cpp) | Build from [whisper.cpp](https://github.com/ggerganov/whisper.cpp) |
| `ollama` | Local LLM inference | [ollama.com](https://ollama.com) |
| `tesseract` | OCR (optional) | System package |

### First-time setup

```bash
solux init      # Guided setup: create config, scaffold workflow, check Ollama
solux doctor    # Verify dependencies (scoped to your workflows by default)
```

`solux init` is the recommended first command. It creates `~/.config/solux/config.toml`, scaffolds a starter workflow, checks Ollama, and prints next steps. See also the [Quick Start guide](QUICK_START.md).

---

## Quick Start

### Summarize a webpage

```bash
solux https://example.com/article
```

The default workflow is `webpage_summary` — it only needs Ollama. No audio stack required.

### Summarize an audio file

```bash
solux run --workflow audio_summary episode.mp3
```

This requires yt-dlp, ffmpeg, and whisper.cpp. Run `solux doctor --workflow audio_summary` to check.

### Summarize a YouTube video in bullet-note format

```bash
solux run --workflow audio_summary "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --mode notes --format markdown
```

### Queue a batch of files and process them in the background

```bash
solux ingest ~/Downloads/podcasts/*.mp3 --workflow audio_summary
solux worker start
solux worker status
```

### Start the web UI

```bash
solux serve
# Open http://localhost:8765
```

---

## Core Concepts

### Context

Every workflow execution carries a **context** (`ctx`) dictionary that flows through each step. Steps read from context and write back to it. The initial context contains:

- `source` — the input string (URL, file path, or any identifier)
- `runtime.*` — flags set by the CLI (`mode`, `format`, `no_cache`, `verbose`, etc.)
- `params` — extra key/value pairs passed at queue time

Each step adds its own keys. For example, `input.webpage_fetch` writes `webpage_text`, and `ai.llm_summarize` writes `summary_text`.

### Modules

A **module** is a Python file that exports a `MODULE = ModuleSpec(...)` object and a `handle(ctx, step) -> ctx` function. Modules are organized into four categories:

- **input** — fetch data from external sources
- **transform** — reshape, clean, or enrich data in-place
- **ai** — call local AI services (Ollama, whisper.cpp)
- **output** — persist or deliver results

### Workflows

A **workflow** is a YAML file that lists an ordered sequence of steps. Each step names a module by its `type` (`category.module_name`) and passes configuration. Workflows live in `~/.config/solux/workflows.d/` or are built into the package.

### Queue

The **queue** is a SQLite database at `~/.local/share/solux/queue/jobs.db`. Jobs move through statuses: `pending → processing → done` (or `failed → dead_letter` after max retries).

### Worker

The **worker** is a long-running process that polls the queue, executes workflows, and handles retries. It hot-reloads modules, workflows, and triggers without restarting.

---

## Configuration

The config file is at `~/.config/solux/config.toml`. Run `solux config` to create it from defaults.

```toml
[paths]
cache_dir = "~/.local/share/solux"

[whisper]
threads = 4
# cli_path = "/usr/local/bin/whisper-cli"
# model_path = "~/.local/share/whisper/ggml-base.en.bin"

[ollama]
base_url = "http://localhost:11434"
model = "qwen3:8b"
# max_transcript_chars = 8000   # Truncate long inputs before LLM call

[yt_dlp]
binary = "yt-dlp"

[ffmpeg]
binary = "ffmpeg"

[workflows]
dir = "~/.config/solux/workflows.d"

[modules]
dir = "~/.config/solux/modules.d"

[triggers]
dir = "~/.config/solux/triggers.d"

[ui]
default_workflow = "webpage_summary"

[security]
mode = "trusted"              # "trusted" or "untrusted"
# webhook_rate_limit = 60     # Integer >= 1; max POST /api/trigger/* requests per IP per minute
# oidc_issuer   = "https://idp.example.com/realms/myrealm"
# oidc_audience = "solux"     # required when oidc_require_auth = true
# oidc_require_auth = false
# oidc_allowed_algs = ["RS256", "PS256"]

[prompts]
# system = "You are a helpful assistant."
# tldr   = "Give a 2-3 sentence summary."
```

**Key paths:**

| Path | Purpose |
|------|---------|
| `~/.config/solux/config.toml` | Main configuration |
| `~/.config/solux/workflows.d/` | User workflow YAML files |
| `~/.config/solux/modules.d/` | User custom module `.py` files |
| `~/.config/solux/triggers.d/` | User trigger YAML files |
| `~/.local/share/solux/` | Runtime data (queue DB, cache, uploads) |

---

## CLI Reference

```
solux [subcommand] [options]
```

If no subcommand is given, `solux <source>` is shorthand for `solux run --workflow <ui.default_workflow> <source>` (`webpage_summary` by default).

### `solux run`

Execute a workflow immediately for a single source.

```bash
solux run [--workflow NAME] [OPTIONS] SOURCE
```

| Option | Default | Description |
|--------|---------|-------------|
| `--workflow NAME` | `ui.default_workflow` (`webpage_summary`) | Workflow to execute |
| `--mode MODE` | `full` | Summary mode: `full`, `tldr`, `outline`, `notes`, `transcript` |
| `--format FORMAT` | `markdown` | Output format: `markdown`, `json`, `text` |
| `--output PATH` | stdout | Write output to file |
| `--timestamps` | off | Include timestamps in transcript/summary |
| `--no-cache` | off | Bypass cached downloads |
| `--verbose` | off | Show step-by-step progress |
| `--quiet-progress` | off | Suppress progress indicators |
| `--dry-run` | off | Parse workflow but do not execute |
| `--model MODEL` | config | Override Ollama model |

**Examples:**

```bash
# Summarize a podcast episode
solux run --workflow audio_summary "https://example.com/episode.mp3"

# Generate bullet notes from a YouTube video
solux run --workflow audio_summary "https://youtube.com/watch?v=..." --mode notes --output notes.md

# Fetch and summarize a webpage, output JSON
solux run --workflow webpage_summary "https://news.ycombinator.com" --format json

# Dry run to validate workflow
solux run --workflow my_workflow source.txt --dry-run
```

### `solux ingest`

Add one or more sources to the background queue without waiting for results.

```bash
solux ingest [--workflow NAME] [OPTIONS] SOURCE [SOURCE ...]
```

Options mirror `solux run` (same flags except `--verbose`, `--dry-run`, `--output`).

```bash
# Queue a directory of podcast files
solux ingest ~/Downloads/podcasts/*.mp3 --workflow audio_summary --mode tldr

# Queue web pages
solux ingest "https://example.com/a" "https://example.com/b" --workflow webpage_summary
```

### `solux worker`

Manage the background worker process.

```bash
solux worker start [--workers N]   # Start worker (default: 1 thread)
solux worker status                 # Show queue counts
solux worker stop                   # Graceful shutdown
```

```bash
# Run 4 parallel workers
solux worker start --workers 4

# Check queue
solux worker status
# Pending: 12  Processing: 4  Done: 103  Failed: 2  Dead-letter: 0
```

### `solux log`

View worker logs.

```bash
solux log           # Print all logs
solux log --no-history  # Skip startup history and show live updates only
```

### `solux workflows`

Manage workflows. All of these are also available in the web UI at `/workflows`.

```bash
solux workflows list           # List all available workflows (built-in + user)
solux workflows show NAME      # Print workflow YAML
solux workflows validate NAME  # Validate workflow without running it
solux workflows examples       # Print example/template YAML for new workflows
solux workflows delete NAME    # Delete a workflow YAML file (--yes to skip prompt)
```

### `solux triggers`

Manage triggers. All of these are also available in the web UI at `/triggers`.

```bash
solux triggers list            # List all triggers in triggers.d/
solux triggers show NAME       # Print a trigger's YAML
solux triggers validate NAME   # Validate a trigger YAML (also checks workflow exists)
solux triggers examples        # Print example/template YAML for new triggers
solux triggers delete NAME     # Delete a trigger YAML file (--yes to skip prompt)
```

> After creating, editing, or deleting a trigger file, restart the worker for the change to take effect: `solux worker stop && solux worker start`.

### `solux modules`

Inspect available modules.

```bash
solux modules list          # List all modules with category and version
solux modules inspect NAME  # Show full module spec (reads, writes, config, deps)
```

```bash
solux modules inspect ai.llm_summarize
```

### `solux serve`

Start the web UI.

```bash
solux serve [--host HOST] [--port PORT]
```

Defaults to `http://localhost:8765`.

### `solux init`

Guided first-run setup. Creates config, scaffolds a starter workflow, checks Ollama, and prints next steps.

```bash
solux init
```

This is idempotent — running it again won't overwrite existing files.

### `solux config`

View and edit the configuration file.

```bash
solux config         # Create config.toml if missing, print it, run doctor
solux config edit    # Open config.toml in $EDITOR (VISUAL / EDITOR / nano / vi)
```

You can also edit the config in the web UI at `/config`. Config changes require restarting `solux serve` to take effect.

### `solux doctor`

Verify the environment. By default, only checks dependencies required by your configured workflows.

```bash
solux doctor                              # scoped to your workflows
solux doctor --all                        # check all dependencies
solux doctor --fix                        # show copy-pasteable fix commands
solux doctor --workflow audio_summary     # check one workflow's deps
```

### `solux examples`

Print example workflow YAML templates. Shorthand for `solux workflows examples`.

```bash
solux examples
```

### `solux cleanup`

Remove cached artifacts.

```bash
solux cleanup [--dry-run] [--yes] [--source-id ID] [--older-than-days N]
```

### `solux retry`

Re-queue failed or dead-letter jobs.

```bash
solux retry
```

### `solux repair`

Recover stuck or orphaned jobs by reconstructing queue state from the filesystem.

```bash
solux repair
```

---

## Workflow Authoring

### Minimal workflow

```yaml
name: my_workflow
description: "Fetch a webpage and summarize it."
steps:
  - name: fetch
    type: input.webpage_fetch
    config: {}
  - name: summarize
    type: ai.llm_summarize
    config:
      mode: tldr
      format: markdown
```

Save as `~/.config/solux/workflows.d/my_workflow.yaml`, then run:

```bash
solux run --workflow my_workflow "https://example.com"
```

### Step anatomy

```yaml
steps:
  - name: step_name          # Human-readable label (required)
    type: category.module    # Module type (required)
    config:                  # Module-specific configuration (optional)
      key: value
    when: "expression"       # Conditional—skip step if false (optional)
    foreach: context_key     # Iterate over a list in context (optional)
    timeout: 60              # Per-step timeout in seconds (optional)
    on_error: workflow_name  # Run this workflow on step failure (optional)
```

### Conditional steps (`when:`)

Use `when:` to skip a step unless a condition is met. The expression is evaluated against the current context using a safe AST evaluator (no `eval()`).

**Supported operators:** `==`, `!=`, `<`, `<=`, `>`, `>=`, `is`, `is not`, `in`, `not in`, `and`, `or`, `not`

```yaml
- name: alert
  type: output.slack_notify
  when: "sentiment[score] > 0.7"
  config:
    webhook_url: "${env:SLACK_WEBHOOK}"
    input_key: summary_text

- name: tag_tech
  type: output.local_db
  when: "classification == 'tech'"
  config:
    table: tech_articles
```

### Iterating over lists (`foreach:`)

Use `foreach:` to run a step once per item in a context list. Solux injects `_item` (current element) and `_index` (zero-based position) into the context for each iteration.

```yaml
- name: summarize_each_message
  type: ai.llm_prompt
  foreach: messages          # Must be a list in context
  config:
    prompt_template: "Summarize this email:\n\n{_item[body]}"
    output_key: output_text
```

### Sub-workflows

Compose workflows by calling one from another with the special `workflow` step type.

```yaml
steps:
  - name: run_transcription
    type: workflow
    config:
      name: audio_summary    # Name of another workflow to execute
```

### Error handling (`on_error:`)

Any step can specify an `on_error` workflow to run if the step fails. When a step raises an exception and `on_error` is set, Solux injects `_error` (the error message) and `_error_step` (the failing step name) into the context, then executes the named workflow.

```yaml
steps:
  - name: risky_extraction
    type: ai.llm_extract
    on_error: extraction_fallback
    config:
      input_key: raw_text
      fields: [name, date, amount]
```

If the error workflow succeeds, execution continues to the next step. If the error workflow also fails, the **original** exception is raised. Steps without `on_error` propagate exceptions normally.

The error-handling workflow can read `_error` and `_error_step` from the context:

```yaml
# extraction_fallback.yaml
name: extraction_fallback
description: "Handle extraction failures gracefully."
steps:
  - name: log_error
    type: output.file_write
    config:
      input_key: _error
      path: errors.log
```

### Parallel foreach

When iterating over a list, add `parallel` to the step config to process items concurrently using a thread pool:

```yaml
- name: embed_chunks
  type: ai.embeddings
  foreach: chunks
  config:
    parallel: 4         # Use 4 worker threads
    input_key: _item
```

When `parallel` is greater than 0, all iterations run in parallel and results are collected in order into `_foreach_results` (a list of per-iteration context dicts). The last iteration's data becomes the final context, matching sequential behavior for backwards compatibility. When `parallel` is 0 or absent, the existing sequential behavior is used.

### Branch steps (`type: branch`)

Route execution to different workflows based on a context value:

```yaml
- name: route_document
  type: branch
  config:
    condition_key: doc_type
    branches:
      report: process_report
      invoice: process_invoice
    default: process_generic
```

The engine looks up `ctx.data[condition_key]`, converts it to a string, matches against the `branches` dict keys, and executes the corresponding workflow. If no match is found, `default` is used. If no default is set and no match exists, a RuntimeError is raised. Branch steps share the sub-workflow cycle detection mechanism—circular references are caught.

### Secrets interpolation

Any config value can reference an environment variable using `${env:VAR_NAME}`. The variable is expanded at runtime.

```yaml
config:
  password: "${env:GMAIL_APP_PASSWORD}"
  webhook_url: "${env:SLACK_WEBHOOK_URL}"
```

### Per-step timeouts

```yaml
- name: slow_ocr
  type: transform.ocr
  timeout: 120    # Mark step timed out after 120 seconds (best effort)
  config:
    lang: eng
```

Timeouts are best-effort (the worker thread cannot be force-killed). Timed-out jobs are marked failed and moved directly to `dead_letter` (no automatic retry).

### Step timings

After a workflow completes, the context contains `_step_timings`—a list of dicts with `name`, `type`, `start`, `end`, and `duration_ms` for each step. Useful for debugging slow pipelines.

---

## Module Reference

### Input modules

#### `input.source_fetch`

Download audio from a URL (YouTube, podcast, direct link) or accept a local file path. Uses `yt-dlp`.

| Config key | Default | Description |
|------------|---------|-------------|
| *(none required)* | | Source comes from `ctx["source"]` |

**Writes:** `audio_input_path`, `display_name`

```yaml
- name: fetch
  type: input.source_fetch
  config: {}
```

---

#### `input.webpage_fetch`

Fetch a URL and extract its text content using Solux's built-in HTML-to-text extractor.

**Reads:** `ctx["source"]` (URL)
**Writes:** `webpage_text`, `display_name`

```yaml
- name: fetch_page
  type: input.webpage_fetch
  config: {}
```

---

#### `input.rss_feed`

Fetch and parse an RSS or Atom feed.

| Config key | Default | Description |
|------------|---------|-------------|
| `url` | *(required)* | Feed URL |
| `limit` | `10` | Maximum items to return |
| `output_key` | `feed_items` | Context key to write results |

**Writes:** `feed_items` (list of `{title, link, summary, published}`), `display_name`

```yaml
- name: fetch_feed
  type: input.rss_feed
  config:
    url: "https://feeds.example.com/podcast.rss"
    limit: 20
```

---

#### `input.folder_watch`

Snapshot a directory and return file paths matching a glob pattern, sorted by modification time.

| Config key | Default | Description |
|------------|---------|-------------|
| `path` | *(required)* | Directory path to scan |
| `pattern` | `*` | Glob pattern (e.g., `*.mp3`) |
| `output_key` | `found_files` | Context key to write results |

**Writes:** `found_files` (list of file paths)

```yaml
- name: scan_dir
  type: input.folder_watch
  config:
    path: ~/Downloads/incoming
    pattern: "*.pdf"
```

---

#### `input.parse_pdf`

Extract text from a PDF file using `pypdf`. Requires `pip install 'solux[pdf]'`.

| Config key | Default | Description |
|------------|---------|-------------|
| `output_key` | `pdf_text` | Context key to write text |
| `pages` | all | Page indices (list) or count (int) |

**Reads:** `ctx["source"]` (file path)
**Writes:** `pdf_text`, `display_name`

```yaml
- name: read_pdf
  type: input.parse_pdf
  config:
    pages: [0, 1, 2]   # First three pages only
```

---

#### `input.email_inbox`

Fetch messages from an IMAP inbox. **Trusted-only** (requires `security.mode = "trusted"`).

| Config key | Default | Description |
|------------|---------|-------------|
| `host` | *(required)* | IMAP server hostname |
| `port` | `993` | IMAP port |
| `username` | *(required)* | Login username |
| `password` | *(required)* | Login password (use `${env:...}`) |
| `folder` | `INBOX` | Mailbox folder name |
| `limit` | `10` | Maximum messages to fetch |
| `unseen_only` | `true` | Fetch only unread messages |

**Writes:** `messages` (list of `{uid, subject, from, date, body, snippet}`), `display_name`

```yaml
- name: fetch_inbox
  type: input.email_inbox
  config:
    host: imap.gmail.com
    username: "${env:GMAIL_USER}"
    password: "${env:GMAIL_APP_PASSWORD}"
    limit: 10
    unseen_only: true
```

---

#### `input.youtube_playlist`

Extract video URLs from a YouTube playlist using `yt-dlp`.

| Config key | Default | Description |
|------------|---------|-------------|
| `output_key` | `video_urls` | Context key for the URL list |
| `limit` | `50` | Maximum video URLs to return |

**Reads:** `ctx["source"]` (playlist URL)
**Writes:** `video_urls`, `playlist_title`, `display_name`

```yaml
- name: get_playlist
  type: input.youtube_playlist
  config:
    limit: 10
```

---

#### `input.s3_watcher`

List objects from an S3-compatible bucket. **Trusted-only**. Requires `pip install 'solux[s3]'`.

| Config key | Default | Description |
|------------|---------|-------------|
| `bucket` | *(required)* | Bucket name |
| `prefix` | `""` | Object key prefix filter |
| `pattern` | `*` | Glob pattern for key matching |
| `aws_access_key_id` | env | AWS/MinIO access key |
| `aws_secret_access_key` | env | AWS/MinIO secret key |
| `endpoint_url` | AWS default | Custom endpoint (e.g., MinIO) |
| `limit` | `100` | Max objects to list |
| `output_key` | `s3_objects` | Context key for results |

**Writes:** `s3_objects` (list of `{key, url, size, etag}`), `display_name`

```yaml
- name: list_bucket
  type: input.s3_watcher
  config:
    bucket: my-bucket
    prefix: "uploads/"
    pattern: "*.mp4"
    aws_access_key_id: "${env:AWS_ACCESS_KEY_ID}"
    aws_secret_access_key: "${env:AWS_SECRET_ACCESS_KEY}"
    endpoint_url: "http://localhost:9000"
```

---

### Transform modules

#### `transform.audio_normalize`

Convert any audio to 16 kHz mono WAV using `ffmpeg`.

**Reads:** `audio_input_path`
**Writes:** `wav_path`

```yaml
- name: normalize
  type: transform.audio_normalize
  config: {}
```

---

#### `transform.text_split`

Split a text string into chunks for further processing.

| Config key | Default | Description |
|------------|---------|-------------|
| `input_key` | `input_text` | Context key to read text from |
| `output_key` | `chunks` | Context key to write chunk list |
| `method` | `paragraph` | Split method: `paragraph`, `sentence`, `fixed` |
| `chunk_size` | `2000` | Chars per chunk (for `fixed` method) |
| `overlap` | `200` | Overlapping chars between chunks |

**Writes:** `chunks` (list of strings)

```yaml
- name: split
  type: transform.text_split
  config:
    input_key: pdf_text
    method: paragraph
```

---

#### `transform.text_clean`

Clean and normalize a text string.

| Config key | Default | Description |
|------------|---------|-------------|
| `input_key` | `input_text` | Context key to read text from |
| `output_key` | `cleaned_text` | Context key to write result |
| `strip_html` | `true` | Remove HTML tags |
| `normalize_whitespace` | `true` | Collapse runs of whitespace |
| `max_chars` | `0` | Truncate to this length (`0` = unlimited) |

**Writes:** `cleaned_text`

```yaml
- name: clean
  type: transform.text_clean
  config:
    input_key: webpage_text
    strip_html: true
    max_chars: 10000
```

---

#### `transform.metadata_extract`

Extract file metadata: filesystem attributes plus format-specific fields (e.g., PDF author, title).

| Config key | Default | Description |
|------------|---------|-------------|
| `input_key` | `ctx.source` | File path |
| `output_key` | `file_metadata` | Context key for result dict |

**Writes:** `file_metadata` (`{title, author, size_bytes, mime_type, ...}`)

```yaml
- name: meta
  type: transform.metadata_extract
  config:
    input_key: audio_input_path
```

---

#### `transform.ocr`

Extract text from an image using Tesseract. Requires `pip install 'solux[ocr]'` and the system `tesseract-ocr` package.

| Config key | Default | Description |
|------------|---------|-------------|
| `input_key` | `ctx.source` | Image file path |
| `output_key` | `ocr_text` | Context key for extracted text |
| `lang` | `eng` | Tesseract language code |

**Writes:** `ocr_text`, `display_name`

```yaml
- name: read_image
  type: transform.ocr
  config:
    lang: eng
```

---

### AI modules

All AI modules require `ollama` running locally (except `ai.whisper_transcribe` which uses `whisper-cli`). Configure the model in `config.toml` under `[ollama]`.

#### `ai.whisper_transcribe`

Transcribe audio using `whisper.cpp`.

| Config key | Default | Description |
|------------|---------|-------------|
| `output_key` | `transcript` | Base key for output |

**Reads:** `wav_path`
**Writes:** `transcript_path`, `transcript_text` (also `{output_key}_path`, `{output_key}_text`)

```yaml
- name: transcribe
  type: ai.whisper_transcribe
  config: {}
```

---

#### `ai.llm_summarize`

Summarize text using Ollama with one of several built-in prompt modes.

| Config key | Default | Description |
|------------|---------|-------------|
| `input_key` | `transcript_text` | Context key to read from |
| `mode` | `full` | `full`, `tldr`, `outline`, `notes`, `transcript` |
| `format` | `markdown` | `markdown`, `json`, `text` |
| `timestamps` | `false` | Include timestamps in output |

**Writes:** `summary_text`, `output_text`, `mode`, `format`, `cache_output_path`, `export_output_path`

```yaml
- name: summarize
  type: ai.llm_summarize
  config:
    input_key: transcript_text
    mode: outline
    format: markdown
```

---

#### `ai.llm_prompt`

Send a custom prompt template to Ollama. Template variables are substituted from context using `{key}` syntax (including nested dict access `{key[field]}`).

| Config key | Default | Description |
|------------|---------|-------------|
| `system_prompt` | config default | System message for the LLM |
| `prompt_template` | *(required)* | Prompt with `{variable}` placeholders |
| `input_key` | auto | Fallback context key if template has `{input}` |
| `output_key` | `llm_output` | Context key for the response |

**Writes:** `llm_output`, `output_text`

```yaml
- name: classify_topic
  type: ai.llm_prompt
  config:
    system_prompt: "You are a topic classifier. Reply with a single word."
    prompt_template: "Classify the topic of this text:\n\n{webpage_text}"
    output_key: topic
```

---

#### `ai.llm_classify`

Classify text into one of a list of categories.

| Config key | Default | Description |
|------------|---------|-------------|
| `categories` | *(required)* | List of category strings |
| `input_key` | auto | Context key to read text from |
| `output_key` | `classification` | Context key for result |
| `system_prompt` | auto | Override system message |

**Writes:** `classification` (string—one of the provided categories)

```yaml
- name: classify
  type: ai.llm_classify
  config:
    input_key: cleaned_text
    categories: [tech, politics, sports, entertainment, science]
```

---

#### `ai.llm_extract`

Extract structured fields from text as a JSON object.

| Config key | Default | Description |
|------------|---------|-------------|
| `fields` | *(required)* | List of field names to extract |
| `input_key` | auto | Context key to read text from |
| `output_key` | `extracted` | Context key for result dict |
| `system_prompt` | auto | Override system message |

**Writes:** `extracted` (dict with one key per field)

```yaml
- name: extract_entities
  type: ai.llm_extract
  config:
    input_key: webpage_text
    fields: [author, publication_date, main_topic, key_quotes]
```

---

#### `ai.llm_sentiment`

Analyze the sentiment of text.

| Config key | Default | Description |
|------------|---------|-------------|
| `input_key` | auto | Context key to read text from |
| `output_key` | `sentiment` | Context key for result |
| `scale` | `pos_neg_neu` | `pos_neg_neu`, `five_point`, or `detailed` |

**Writes:** `sentiment` (`{label, score, explanation}`)

```yaml
- name: analyze_sentiment
  type: ai.llm_sentiment
  config:
    input_key: cleaned_text
    scale: five_point
```

---

#### `ai.embeddings`

Generate a vector embedding for text using Ollama.

| Config key | Default | Description |
|------------|---------|-------------|
| `input_key` | auto | Context key to read text from |
| `output_key` | `embedding` | Context key for float list |
| `model` | config | Override Ollama model |

**Writes:** `embedding` (list of floats)

```yaml
- name: embed
  type: ai.embeddings
  config:
    input_key: summary_text
    output_key: embedding
```

---

### Output modules

All output modules marked **trusted-only** require `security.mode = "trusted"` in `config.toml`.

#### `output.file_write`

Write output text to a file.

| Config key | Default | Description |
|------------|---------|-------------|
| `input_key` | `output_text` | Context key to read content from |
| `mode` | `full` | Summary mode label (used in filename) |
| `format` | `markdown` | File extension hint |

**Writes:** `export_output_path`

```yaml
- name: write_file
  type: output.file_write
  config:
    input_key: summary_text
    format: markdown
```

---

#### `output.webhook`

POST data as JSON to an HTTP endpoint. **Trusted-only.**
Logs redact the endpoint to `scheme://host` to avoid leaking path/query secrets.

| Config key | Default | Description |
|------------|---------|-------------|
| `url` | *(required)* | Endpoint URL |
| `method` | `POST` | HTTP method |
| `input_key` | `output_text` | Context key for payload |
| `headers` | `{}` | Extra HTTP headers |
| `wrap_key` | `None` | Wrap payload under this JSON key |
| `raise_on_error` | `true` | Raise exception on non-2xx response |

**Writes:** `webhook_status_code`

```yaml
- name: send_webhook
  type: output.webhook
  config:
    url: "https://hooks.example.com/notify"
    input_key: summary_text
    headers:
      Authorization: "Bearer ${env:WEBHOOK_TOKEN}"
```

---

#### `output.local_db`

Append a record to a local SQLite table. **Trusted-only.**

| Config key | Default | Description |
|------------|---------|-------------|
| `db_path` | cache dir | Path to SQLite database |
| `table` | `records` | Table name |
| `input_key` | `output_text` | Context key for content |

**Writes:** `db_record_id`

```yaml
- name: store
  type: output.local_db
  config:
    db_path: ~/data/articles.db
    table: summaries
    input_key: summary_text
```

---

#### `output.vector_store`

Upsert text + embedding into a ChromaDB collection. **Trusted-only.** Requires `pip install 'solux[vector]'`.

| Config key | Default | Description |
|------------|---------|-------------|
| `collection` | `solux` | ChromaDB collection name |
| `db_path` | `~/.local/share/solux/chroma` | Path to ChromaDB directory |
| `embedding_key` | `embedding` | Context key for embedding float list |
| `text_key` | `output_text` | Context key for text content |
| `id_key` | `""` | Context key for document ID (empty = use `ctx.source_id`) |

**Writes:** `vector_store_id`

```yaml
- name: index
  type: output.vector_store
  config:
    collection: articles
    embedding_key: embedding
    text_key: summary_text
```

---

#### `output.email_send`

Send an email via SMTP. **Trusted-only.**

| Config key | Default | Description |
|------------|---------|-------------|
| `smtp_host` | *(required)* | SMTP server hostname |
| `smtp_port` | `587` | SMTP port |
| `smtp_user` | *(required)* | Login username |
| `smtp_password` | *(required)* | Login password |
| `from_addr` | *(required)* | Sender address |
| `to_addr` | *(required)* | Recipient address |
| `subject_template` | `"Solux: {display_name}"` | Email subject (supports `{variable}`) |
| `input_key` | `output_text` | Context key for email body |
| `use_tls` | `true` | Use STARTTLS |

**Writes:** `email_sent`, `email_message_id`

```yaml
- name: send_digest
  type: output.email_send
  config:
    smtp_host: smtp.gmail.com
    smtp_user: "${env:GMAIL_USER}"
    smtp_password: "${env:GMAIL_APP_PASSWORD}"
    from_addr: "${env:GMAIL_USER}"
    to_addr: me@example.com
    subject_template: "Daily Digest: {display_name}"
    input_key: summary_text
```

---

#### `output.obsidian_vault`

Write a note to an Obsidian vault with YAML frontmatter. **Trusted-only.**

| Config key | Default | Description |
|------------|---------|-------------|
| `vault_path` | *(required)* | Path to Obsidian vault root |
| `folder` | `"Solux"` | Subfolder within vault |
| `input_key` | `output_text` | Context key for note body |
| `filename_key` | `display_name` | Context key for note filename |
| `tags` | `[]` | YAML frontmatter tags |
| `overwrite` | `false` | Overwrite if note exists |

**Writes:** `obsidian_note_path`

```yaml
- name: save_note
  type: output.obsidian_vault
  config:
    vault_path: ~/Documents/MyVault
    folder: Podcasts
    tags: [ai-summary, podcast]
```

---

#### `output.slack_notify`

Send a message to a Slack channel via incoming webhook. **Trusted-only.**
Logs redact the webhook URL to `scheme://host` to avoid leaking path/query secrets.

| Config key | Default | Description |
|------------|---------|-------------|
| `webhook_url` | *(required)* | Slack incoming webhook URL |
| `input_key` | `output_text` | Context key for message content |
| `message_template` | `None` | Template with `{variable}` placeholders; overrides `input_key` |
| `username` | `"Solux"` | Bot display name |
| `icon_emoji` | `":robot_face:"` | Bot emoji icon |

**Writes:** `slack_status_code`

```yaml
- name: notify_slack
  type: output.slack_notify
  config:
    webhook_url: "${env:SLACK_WEBHOOK_URL}"
    message_template: "New summary ready: *{display_name}*\n\n{summary_text}"
```

---

#### `output.vinsium_node`

Forward workflow data to a remote Solux instance. **Trusted-only.**

| Config key | Default | Description |
|------------|---------|-------------|
| `node_url` | *(required)* | Remote Solux base URL |
| `auth_token` | `None` | Bearer token for remote auth |
| `workflow_name` | *(required)* | Workflow to trigger on remote node |
| `input_key` | `output_text` | Context key for payload |
| `verify_ssl` | `true` | Verify TLS certificate |

**Writes:** `vinsium_response_status`, `vinsium_job_id`

```yaml
- name: forward
  type: output.vinsium_node
  config:
    node_url: "https://solux.internal"
    auth_token: "${env:REMOTE_TOKEN}"
    workflow_name: archive_summary
    input_key: summary_text
```

---

### Meta modules

#### `workflow` (sub-workflow)

Execute another named workflow as a step. See [Sub-workflows](#sub-workflows) and [Using sub-workflows](#using-sub-workflows) for details.

| Config key | Default | Description |
|------------|---------|-------------|
| `name` | *(required)* | Name of the workflow to execute |

---

#### `branch`

Conditional routing: select and execute a workflow based on a context value. See [Branch steps](#branch-steps-type-branch) for details.

| Config key | Default | Description |
|------------|---------|-------------|
| `condition_key` | *(required)* | Context key whose value selects the branch |
| `branches` | *(required)* | Mapping of value → workflow name |
| `default` | `None` | Fallback workflow when no branch matches |

```yaml
- name: route
  type: branch
  config:
    condition_key: doc_type
    branches:
      report: process_report
      invoice: process_invoice
    default: process_generic
```

---

## Background Worker & Queue

The worker is a long-running process that polls the SQLite queue and executes jobs.

### Starting the worker

```bash
# Single worker (default)
solux worker start

# Four parallel workers
solux worker start --workers 4
```

The worker process continues until stopped and hot-reloads modules, workflows, and triggers every 5 seconds—so you can edit them without restarting.

### Checking queue status

```bash
solux worker status
```

Output:

```
Pending:      12
Processing:    4
Done:        103
Failed:        2
Dead-letter:   0
```

### Stopping the worker

```bash
solux worker stop
```

### Retry behavior

When a step fails, Solux schedules an automatic retry with **exponential backoff**:

| Attempt | Delay before retry |
|---------|--------------------|
| 1st failure | 30 seconds |
| 2nd failure | 60 seconds |
| 3rd failure | 120 seconds |
| 4th failure | Moved to `dead_letter` (no more retries) |

Timeout failures are an exception: they skip backoff and go directly to `dead_letter`.

Max retries default to 3 and can be overridden per job at ingest time.

Failed jobs that have exhausted their retries remain in the queue as `dead_letter` for inspection. Use `solux retry` to manually re-queue them.

### Viewing logs

```bash
solux log          # Print all worker log entries
solux log --no-history   # Skip startup history and show live updates only
```

---

## Triggers

Triggers allow Solux to automatically enqueue jobs based on external events without manual intervention. Trigger definitions live in `~/.config/solux/triggers.d/*.yaml`.

The worker must be running for triggers to fire.
The built-in `daily_briefing_cron` and `email_inbox_monitor` templates default to the source-agnostic `trigger_event_note` workflow so they execute safely before you wire in a production pipeline.

### Trigger file format

```yaml
name: my_trigger            # Unique trigger name
enabled: false              # Start disabled until you explicitly enable it
type: folder_watch          # Trigger type
workflow: audio_summary     # Workflow to enqueue
params:                     # Extra params passed to each job
  mode: tldr
config:                     # Type-specific configuration
  path: ~/Downloads/incoming
  pattern: "*.mp3"
  interval: 30
```

### Trigger types

#### `folder_watch`

Poll a directory for new files matching a pattern.

```yaml
name: watch_incoming_audio
enabled: false
type: folder_watch
workflow: audio_summary
params:
  mode: full
config:
  path: ~/Downloads/podcasts
  pattern: "*.mp3"
  interval: 60           # Seconds between scans (default: 30)
```

Each new file (not previously seen) is enqueued as a separate job. Symlinks inside the watch directory that resolve outside it are silently skipped and logged as a warning—only files physically located within `path` are enqueued.

---

#### `rss_poll`

Poll an RSS or Atom feed and enqueue new items.

```yaml
name: tech_news
enabled: false
type: rss_poll
workflow: webpage_summary
params:
  mode: tldr
config:
  url: "https://hnrss.org/frontpage"
  interval: 300          # Seconds between polls (default: 300)
```

Each new item's link is enqueued as a job source.

---

#### `cron`

Run a workflow on a schedule. Supports standard cron expressions or an interval in seconds.

```yaml
# Using cron expression (runs at 08:00 UTC daily)
name: morning_digest
enabled: false
type: cron
workflow: email_digest
config:
  schedule: "0 8 * * *"

# Using interval
name: hourly_check
enabled: false
type: cron
workflow: my_workflow
config:
  interval_seconds: 3600
```

---

#### `email_poll`

Poll an IMAP inbox and enqueue jobs for new messages.

```yaml
name: inbox_trigger
enabled: false
type: email_poll
workflow: email_digest
config:
  host: imap.gmail.com
  port: 993
  username: "${env:GMAIL_USER}"
  password: "${env:GMAIL_APP_PASSWORD}"
  folder: INBOX
  interval_seconds: 120
```

`email_poll` uses at-least-once delivery semantics: a message UID is marked seen only after enqueue succeeds. If enqueue fails transiently, the same message may be enqueued again on a later poll.

---

#### Inbound webhook (HTTP trigger)

Any external system can enqueue a job via HTTP POST without a trigger file:

```bash
curl -X POST http://localhost:8765/api/trigger/webpage_summary \
  -H "Content-Type: application/json" \
  -d '{"source": "https://example.com/new-article", "mode": "tldr"}'
```

The web server (`solux serve`) must be running for inbound webhooks.
`source` must be a scalar (`string`, `number`, `boolean`, or `null`). Objects/arrays are rejected with HTTP 400. If omitted or `null`, Solux uses `webhook://{workflow_name}`.

Trigger dedupe state is stored per cache directory at `<cache_dir>/triggers/trigger_state.db` (default: `~/.local/share/solux/triggers/trigger_state.db`).

---

## Web UI

Start the web server:

```bash
solux serve                    # http://localhost:8765
solux serve --host 0.0.0.0    # Listen on all interfaces
solux serve --port 9000        # Custom port
```

If you bind to a non-local interface without OIDC auth enabled, Solux prints a startup warning.
For browser-originated POST routes, Solux enforces same-origin checks (`Sec-Fetch-Site`, `Origin`, `Referer`) to reduce CSRF risk. `/api/trigger/{workflow}` is intentionally exempt so external systems (including hosts on a VPN) can submit webhook jobs.

Solux is **terminal-first**: every operation available in the web UI is also available as a CLI command. The UI is a convenience layer.

### Pages

| URL | Terminal equivalent | Description |
|-----|--------------------|----|
| `/` | `solux log` | Dashboard: job queue, source browser, output viewer |
| `/workflows` | `solux workflows list` | List all workflows; link to editor |
| `/workflow/{name}` | `solux workflows show/validate NAME` | YAML editor with validation and delete |
| `/workflow/new?template=NAME` | `solux workflows examples` | Create workflow from a template |
| `/triggers` | `solux triggers list` | List all triggers; link to editor |
| `/trigger/{name}` | `solux triggers show/validate NAME` | YAML editor for triggers with delete |
| `/trigger/new?template=NAME` | `solux triggers examples` | Create trigger from a template |
| `/config` | `solux config` / `solux config edit` | View and edit `config.toml` |
| `/examples` | `solux workflows examples` / `solux triggers examples` | Browse all example templates |
| `/modules` | `solux modules list` | Module catalog |
| `/history` | `solux log` | Job run history (paginated, 100/page); toolbar to retry all failed or clear dead-letter jobs |
| `/healthz` | — | Health check (unauthenticated); returns `{"status":"ok","queue":{...}}` |

> **Config changes** (`/config`) take effect after restarting `solux serve`.
> **Trigger changes** (`/triggers`) take effect after restarting the worker (`solux worker stop && solux worker start`).

### Live updates

The dashboard subscribes to `/events`—a Server-Sent Events stream that pushes queue counts and job status updates every 2 seconds, so you see real-time progress without manual refresh. If OIDC auth is required, the same Bearer token requirement applies to `/events`.

### Triggering jobs from the UI

Use the dashboard (`/`) URL/file ingest controls to enqueue jobs from the browser. The API endpoint `POST /api/trigger/{workflow}` is also available for external systems.

### Payload size limits

POST requests are subject to per-route size limits:

| Route | Max size |
|-------|----------|
| `/api/trigger/{workflow}` | 1 MiB |
| `/ingest-file` | 500 MiB |
| All other POST routes | 2 MiB |

---

## Security

### Security modes

Solux has two security modes configured in `config.toml`:

```toml
[security]
mode = "trusted"     # or "untrusted"
```

| Mode | Behavior |
|------|---------|
| `trusted` | All modules available |
| `untrusted` | Blocks "trusted-only" modules and network-enabled workflow steps |

**Trusted-only modules** (blocked in `untrusted` mode):
`email_inbox`, `s3_watcher`, `webhook`, `local_db`, `vector_store`, `email_send`, `obsidian_vault`, `slack_notify`, `vinsium_node`

In `untrusted` mode, URL-based built-ins that still fetch over HTTP outside workflow execution (for example RSS polling triggers) validate each redirect hop and resolve hostnames to block private/loopback targets.

All XML parsing (RSS feeds, Atom feeds) uses `defusedxml` to prevent XML entity expansion attacks (billion laughs, XXE).

Use `untrusted` mode when running workflows from sources you do not fully control, such as community-shared workflow YAML files.

### Webhook signature verification

To authenticate inbound webhook requests (`POST /api/trigger/{workflow}`), set a shared HMAC-SHA256 secret in `config.toml`:

```toml
[security]
webhook_secret = "my-shared-secret"
```

Callers must include an `X-Solux-Signature` header with the HMAC hex digest:

```
X-Solux-Signature: sha256=<hex-digest>
```

Example with `curl`:

```bash
SECRET="my-shared-secret"
BODY='{"source": "https://example.com/article"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/.*= //')
curl -X POST http://localhost:8765/api/trigger/webpage_summary \
  -H "Content-Type: application/json" \
  -H "X-Solux-Signature: sha256=$SIG" \
  -d "$BODY"
```

When `webhook_secret` is set:
- Missing signature header returns HTTP 401.
- Invalid signature returns HTTP 403.

When `webhook_secret` is empty or unset, webhooks are accepted without signature checks.

### Webhook rate limiting

Solux enforces a per-IP sliding-window rate limit on `POST /api/trigger/*` to prevent abuse. The default is 60 requests per minute per source IP; requests that exceed it receive HTTP 429.
`webhook_rate_limit` must be an integer `>= 1`; invalid values fail config load.

Configure the limit in `config.toml`:

```toml
[security]
webhook_rate_limit = 120   # Raise to 120 if you have high-volume integrations
```

For memory safety, Solux keeps this rate-limit state bounded by evicting stale and oldest entries.

### OIDC authentication for the web UI

The web UI can require a valid JWT token from an external identity provider (e.g., Keycloak, Auth0, Okta).

Enable it in `config.toml`:

```toml
[security]
oidc_issuer    = "https://idp.example.com/realms/myrealm"
oidc_audience  = "solux"
oidc_require_auth = true
oidc_allowed_algs = ["RS256", "PS256"]   # optional
```

Install the OIDC extra:

```bash
pip install 'solux[oidc]'
```

Callers must include `Authorization: Bearer <jwt>` on all routes except `/healthz`. This includes `/events` and `POST /api/trigger/{workflow}` when auth is required. Solux fetches the JWKS from `{issuer}/.well-known/jwks.json` and validates the token signature, expiration, audience, and issuer.
`oidc_audience` must be set when `oidc_require_auth = true`; Solux fails closed if it is missing.
By default, only asymmetric JWT algorithms are accepted (`RS*`, `PS*`, `ES*`).

---

## Writing Custom Modules

Drop a `.py` file into `~/.config/solux/modules.d/` to add a new module. The worker hot-reloads it within 5 seconds.

### Module skeleton

```python
from solux.modules.spec import ConfigField, ContextKey, ModuleSpec

def handle(ctx, step):
    config = step.config
    input_key = str(config.get("input_key", "output_text"))
    output_key = str(config.get("output_key", "my_output"))

    text = str(ctx.data.get(input_key, ""))

    # Your logic here
    result = text.upper()

    ctx.data[output_key] = result
    return ctx


MODULE = ModuleSpec(
    name="my_module",
    version="1.0.0",
    category="transform",
    description="What this module does.",
    handler=handle,
    config_schema=(
        ConfigField(name="input_key", default="output_text", description="Context key to read."),
        ConfigField(name="output_key", default="my_output", description="Context key to write."),
    ),
    reads=(ContextKey("output_text", "Input text"),),
    writes=(ContextKey("my_output", "Transformed text"),),
    safety="safe",  # Use "trusted_only" for sensitive modules.
)
```

### Using your module in a workflow

```yaml
name: my_workflow
steps:
  - name: fetch
    type: input.webpage_fetch
    config: {}
  - name: shout
    type: transform.my_module
    config:
      input_key: webpage_text
      output_key: shouted_text
```

### Module guidelines

- `handle()` must always return `ctx` (even if unmodified).
- Raise a plain `Exception` to trigger retry logic; use specific messages for clarity.
- Read from context using `.get()` with safe defaults; never assume a key exists.
- Set `safety="trusted_only"` if your module accesses credentials, the network, the filesystem, or other sensitive resources.
- List all non-stdlib `dependencies` so `solux doctor` can advise users.

---

## Secrets Management

Never hardcode credentials in workflow YAML. Use environment variable interpolation instead:

```yaml
config:
  password: "${env:MY_PASSWORD}"
```

Solux expands `${env:VAR_NAME}` at workflow load time. If a variable is missing, it expands to an empty string by default. Set `security.strict_env_vars = true` to fail fast on missing variables.

**Recommended approach:**

1. Store secrets in a `.env` file (never commit this file).
2. Source it before running Solux:

```bash
source ~/.config/solux/.env && solux worker start
```

Or use a secrets manager (Vault, 1Password CLI, etc.) to inject environment variables into the process.

---

## Advanced Patterns

### Pipeline: RSS feed → classify → conditional Slack alert

```yaml
name: rss_alert
description: "Fetch RSS, classify each item, alert on tech news."
steps:
  - name: fetch_feed
    type: input.rss_feed
    config:
      url: "https://hnrss.org/frontpage"
      limit: 20

  - name: fetch_each_page
    type: input.webpage_fetch
    foreach: feed_items
    config: {}   # ctx["source"] is set from _item[link] automatically

  - name: classify_each
    type: ai.llm_classify
    foreach: feed_items
    config:
      input_key: webpage_text
      categories: [tech, business, science, other]
      output_key: classification

  - name: alert_tech
    type: output.slack_notify
    when: "classification == 'tech'"
    config:
      webhook_url: "${env:SLACK_WEBHOOK_URL}"
      message_template: "Tech article: {display_name}\n{webpage_text[:500]}"
```

### Pipeline: PDF ingestion → embed → vector search

```yaml
name: pdf_index
description: "Extract, chunk, embed, and store a PDF."
steps:
  - name: read_pdf
    type: input.parse_pdf
    config: {}

  - name: chunk
    type: transform.text_split
    config:
      input_key: pdf_text
      method: paragraph
      output_key: chunks

  - name: embed_each_chunk
    type: ai.embeddings
    foreach: chunks
    config:
      input_key: _item
      output_key: embedding

  - name: store
    type: output.vector_store
    config:
      collection: documents
      embedding_key: embedding
      text_key: _item
```

### Pipeline: Audio → transcribe → extract → email

```yaml
name: meeting_notes
description: "Transcribe a meeting recording and email extracted action items."
steps:
  - name: fetch
    type: input.source_fetch
    config: {}

  - name: normalize
    type: transform.audio_normalize
    config: {}

  - name: transcribe
    type: ai.whisper_transcribe
    config: {}

  - name: extract_actions
    type: ai.llm_extract
    config:
      input_key: transcript_text
      fields: [action_items, decisions, participants, next_meeting_date]
      output_key: extracted

  - name: format_email
    type: ai.llm_prompt
    config:
      prompt_template: |
        Write a professional meeting notes email based on these extracted details:
        Action items: {extracted[action_items]}
        Decisions: {extracted[decisions]}
        Participants: {extracted[participants]}
      output_key: output_text

  - name: send_email
    type: output.email_send
    config:
      smtp_host: smtp.gmail.com
      smtp_user: "${env:GMAIL_USER}"
      smtp_password: "${env:GMAIL_APP_PASSWORD}"
      from_addr: "${env:GMAIL_USER}"
      to_addr: team@example.com
      subject_template: "Meeting Notes: {display_name}"
```

### Using sub-workflows

Break large workflows into reusable pieces:

```yaml
# ~/.config/solux/workflows.d/fetch_and_clean.yaml
name: fetch_and_clean
steps:
  - name: fetch
    type: input.webpage_fetch
    config: {}
  - name: clean
    type: transform.text_clean
    config:
      input_key: webpage_text
      strip_html: true
      max_chars: 15000
```

```yaml
# ~/.config/solux/workflows.d/full_pipeline.yaml
name: full_pipeline
steps:
  - name: prepare
    type: workflow
    config:
      name: fetch_and_clean    # Run sub-workflow first

  - name: summarize
    type: ai.llm_summarize
    config:
      input_key: cleaned_text
      mode: notes
```

### Using branch for document routing

Route documents to different processing pipelines based on classification:

```yaml
# ~/.config/solux/workflows.d/smart_router.yaml
name: smart_router
description: "Classify a document and route to the appropriate pipeline."
steps:
  - name: classify
    type: ai.llm_classify
    config:
      input_key: raw_text
      categories: [report, invoice, memo, contract]
      output_key: doc_type

  - name: route
    type: branch
    config:
      condition_key: doc_type
      branches:
        report: process_report
        invoice: process_invoice
        contract: process_contract
      default: process_generic
```

### Using on_error with fallback workflows

Gracefully handle failures in critical pipelines:

```yaml
name: resilient_pipeline
description: "Extract data with fallback on failure."
steps:
  - name: extract_structured
    type: ai.llm_extract
    on_error: manual_review_queue
    config:
      input_key: raw_text
      fields: [patient_name, diagnosis, date]
      output_key: extracted

  - name: save
    type: output.file_write
    config:
      input_key: extracted
```

### Using parallel foreach for batch processing

Process large lists concurrently:

```yaml
name: batch_embeddings
description: "Chunk a document and embed all chunks in parallel."
steps:
  - name: read_pdf
    type: input.parse_pdf
    config: {}

  - name: chunk
    type: transform.text_split
    config:
      input_key: pdf_text
      method: paragraph
      output_key: chunks

  - name: embed_all
    type: ai.embeddings
    foreach: chunks
    config:
      parallel: 8
      input_key: _item
      output_key: embedding
```

### Dry run and validation

Before running a new workflow in production, validate it:

```bash
# Parse and validate workflow YAML (does not execute)
solux run --workflow my_workflow source.txt --dry-run

# Validate workflow definition
solux workflows validate my_workflow
```

---

## Deployment

### Docker

A `Dockerfile` and `docker-compose.yml` are provided in the repository root.

**Quick start:**

```bash
docker compose up -d
```

This brings up three services: `ollama` (LLM server), `server` (web UI on port 8765), and `worker` (background processor). Config and data are persisted via Docker volumes.

Place your `config.toml` and workflow files in the `solux_config` volume, or bind-mount a local directory:

```bash
mkdir -p ./my-config ./my-data
SOLUX_CONFIG_MOUNT=./my-config SOLUX_DATA_MOUNT=./my-data docker compose up -d
```

By default, compose publishes ports on `127.0.0.1` only to avoid accidental LAN exposure. The image includes `ffmpeg` and `yt-dlp` but not `whisper-cli`. For audio transcription, mount the whisper binary and model into the container or build a custom image.

If you intentionally expose ports beyond localhost, enable `oidc_require_auth = true` first.

#### Health checks

The `/healthz` endpoint is unauthenticated and returns HTTP 200 with queue counts:

```json
{"status": "ok", "queue": {"pending": 3, "processing": 1, "done": 47, "failed": 0, "dead_letter": 0}}
```

Use it as a Docker health check:

```yaml
healthcheck:
  test: ["CMD", "curl", "-sf", "http://localhost:8765/healthz"]
  interval: 30s
  timeout: 5s
  retries: 3
```

Or in a load balancer upstream check. `/healthz` always returns `status: ok` if Solux is reachable—it does not check Ollama or whisper availability.

### systemd

Hardened unit files are at `contrib/systemd/`:

```bash
sudo cp contrib/systemd/solux-server.service /etc/systemd/system/
sudo cp contrib/systemd/solux-worker.service /etc/systemd/system/
sudo useradd --system --create-home solux
sudo systemctl daemon-reload
sudo systemctl enable --now solux-server solux-worker
```

Security hardening includes `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, and `PrivateTmp`. Edit `ReadWritePaths` if your paths differ from defaults.

Check status:

```bash
sudo systemctl status solux-server solux-worker
journalctl -u solux-worker -f

# Confirm the server is healthy
curl -s http://localhost:8765/healthz
```

---

## Troubleshooting

### `solux doctor` failures

Run `solux doctor --fix` to identify missing dependencies with copy-pasteable commands. Common fixes:

| Problem | Fix |
|---------|-----|
| `whisper-cli` not found | Build from [whisper.cpp](https://github.com/ggerganov/whisper.cpp) and set `whisper.cli_path` in config |
| `ffmpeg` not found | `apt install ffmpeg` or `brew install ffmpeg` |
| `yt-dlp` not found | `pip install yt-dlp` |
| Ollama not reachable | Start Ollama with `ollama serve` and pull a model (`ollama pull qwen3:8b`) |
| `tesseract` not found | `apt install tesseract-ocr` and `pip install 'solux[ocr]'` |

### Jobs stuck in `processing`

If the worker crashed while processing, jobs remain in `processing` state. Use repair to recover them:

```bash
solux repair
```

### Checking step timings

After a job completes, its context contains `_step_timings`. View it by running with verbose output:

```bash
solux run --workflow my_workflow source.txt --verbose
```

### Common YAML mistakes

- **Wrong step type**: Use `input.webpage_fetch`, not `webpage_fetch`. Always include the category prefix.
- **Missing required config**: Check `solux modules inspect <type>` to see required fields.
- **`when:` expression syntax**: Only use supported operators; quotes around string values are required: `when: "classification == 'tech'"`.
- **`foreach:` on non-list**: The referenced context key must be a list at runtime.

### Secrets not expanding

Ensure the environment variable is exported before Solux runs:

```bash
export MY_SECRET=value
solux run --workflow my_workflow source.txt
```

Or source a `.env` file: `source ~/.config/solux/.env`.

### Module not found after adding to `modules.d/`

The worker hot-reloads every 5 seconds. Wait a moment, or restart it. For `solux run`, the module loads immediately on each invocation.

Check for syntax errors in your module:

```bash
python ~/.config/solux/modules.d/my_module.py
```

### Checking the queue database directly

The SQLite queue is at `~/.local/share/solux/queue/jobs.db`:

```bash
sqlite3 ~/.local/share/solux/queue/jobs.db "SELECT status, count(*) FROM jobs GROUP BY status;"
sqlite3 ~/.local/share/solux/queue/jobs.db "SELECT job_id, workflow_name, status, error FROM jobs WHERE status IN ('failed','dead_letter');"
```

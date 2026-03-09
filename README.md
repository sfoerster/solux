# solus

`solus` is a local-first AI workflow engine (think "Zapier for local AI") that chains:

`inputs -> transforms -> local LLM steps -> outputs`

Everything runs on your machine — no cloud APIs required. Workflows are composable via YAML, and the module system is extensible: drop a `.py` file in `~/.config/solus/modules.d/` and use it in any workflow.

Project process docs:
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODEOWNERS`
- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `docs/CONTRIBUTOR_IP.md`
- `docs/legal/CLA_TEMPLATE.md`
- `docs/legal/CAA_TEMPLATE.md`

## Quick Start (60 Seconds)

Only requires Ollama — no ffmpeg, whisper, or yt-dlp needed for your first run.

```bash
pip install -e .
solus init
solus https://example.com/any-article
```

`solus init` creates your config, scaffolds a starter workflow, checks Ollama, and prints next steps. If doctor reports a missing model, pull it:

```bash
ollama pull qwen3:8b
```

The default workflow is `webpage_summary` (fetch + summarize). For audio transcription, see [docs/QUICK_START.md](docs/QUICK_START.md).

> **Full quick start guide:** [docs/QUICK_START.md](docs/QUICK_START.md)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        solus workflow run                            │
│                                                                      │
│  Source (URL / file / folder)                                        │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────┐    enqueue    ┌──────────────────────────────────┐ │
│  │  CLI / API  │──────────────▶│  SQLite Queue  (WAL mode)        │ │
│  │  Triggers   │               │  pending → processing → done     │ │
│  └─────────────┘               └──────────────┬───────────────────┘ │
│                                               │ claim (atomic)       │
│                                               ▼                      │
│                                    ┌──────────────────┐             │
│                                    │  Worker Thread   │             │
│                                    │  (poll / retry / │             │
│                                    │   dead-letter)   │             │
│                                    └────────┬─────────┘             │
│                                             │                        │
│                                             ▼                        │
│                                  ┌──────────────────┐               │
│                                  │ Workflow Loader   │               │
│                                  │ YAML + secrets   │               │
│                                  │ interpolation    │               │
│                                  └────────┬─────────┘               │
│                                           │                         │
│                                           ▼                         │
│                              ┌────────────────────────┐             │
│                              │   Workflow Engine       │             │
│                              │  for each Step:         │             │
│                              │  validate → when? →     │             │
│                              │  foreach? → timeout →   │             │
│                              │  run → on_error? →      │             │
│                              │  record timing          │             │
│                              └───────────┬────────────┘             │
│                                          │                          │
│              ┌───────────────────────────┼──────────────────┐       │
│              ▼               ▼           ▼          ▼        ▼      │
│         ┌────────┐    ┌───────────┐  ┌──────┐  ┌────────┐  ┌──────┐ │
│         │ input  │    │ transform │  │  ai  │  │ output │  │ meta │ │
│         │ fetch  │    │ split /   │  │ llm  │  │ file / │  │ sub- │ │
│         │ rss /  │    │ clean /   │  │ whis-│  │ web-   │  │ work-│ │
│         │ email  │    │ ocr       │  │ per  │  │ hook / │  │ flow/│ │
│         └────────┘    └───────────┘  └──────┘  │ email  │  │branch│ │
│                                                 └────────┘  └──────┘ │
│                                                 └────────┘           │
└─────────────────────────────────────────────────────────────────────┘
```

## Built-in Workflows

- **audio_summary** — Download/transcribe/summarize podcasts, YouTube, and audio files
- **webpage_summary** — Fetch a webpage and summarize its content

## Built-in Modules

### Input

| Step type | Description |
|-----------|-------------|
| `input.source_fetch` | Fetch audio from URL or local file (yt-dlp) |
| `input.webpage_fetch` | Fetch and extract text from a webpage |
| `input.rss_feed` | Fetch and parse an RSS or Atom feed |
| `input.folder_watch` | Snapshot a folder for files matching a pattern |
| `input.parse_pdf` | Extract text from a PDF file (requires `pip install 'solus[pdf]'`) |
| `input.email_inbox` | Fetch messages from an IMAP inbox |
| `input.youtube_playlist` | List video URLs from a YouTube playlist via yt-dlp |
| `input.s3_watcher` | List objects from an S3 or MinIO bucket (requires `pip install 'solus[s3]'`) |

### Transform

| Step type | Description |
|-----------|-------------|
| `transform.audio_normalize` | Normalize audio with ffmpeg |
| `transform.text_split` | Split text into chunks by paragraph, sentence, or fixed size |
| `transform.text_clean` | Strip HTML, normalize whitespace, truncate |
| `transform.metadata_extract` | Extract filesystem and format metadata from a file |
| `transform.ocr` | Extract text from an image using Tesseract OCR (requires `pip install 'solus[ocr]'`) |

### AI

| Step type | Description |
|-----------|-------------|
| `ai.whisper_transcribe` | Transcribe audio with whisper.cpp |
| `ai.llm_summarize` | Summarize text using a local LLM via Ollama |
| `ai.llm_prompt` | Send configurable prompt templates to a local LLM |
| `ai.llm_classify` | Classify text into one of a set of categories using Ollama |
| `ai.llm_extract` | Extract structured fields from text as JSON using Ollama |
| `ai.llm_sentiment` | Analyze sentiment (pos/neg/neu, 5-point, or detailed) using Ollama |
| `ai.embeddings` | Generate text embeddings via Ollama's `/api/embeddings` endpoint |

### Output

| Step type | Description |
|-----------|-------------|
| `output.file_write` | Write output text to a file |
| `output.webhook` | Send context data as a JSON HTTP request to a webhook URL |
| `output.local_db` | Write context data to a local SQLite database |
| `output.vector_store` | Upsert text (and optional embedding) into ChromaDB (requires `pip install 'solus[vector]'`) |
| `output.email_send` | Send an email via SMTP (stdlib, no new deps) |
| `output.obsidian_vault` | Write a note with YAML frontmatter to an Obsidian vault |
| `output.slack_notify` | Send a message to Slack via incoming webhook |
| `output.vinsium_node` | POST results to a remote Vinsium-hosted Solus node |

### Meta

| Step type | Description |
|-----------|-------------|
| `workflow` | Execute another named workflow as a sub-workflow step |
| `branch` | Conditional routing: select a workflow to execute based on a context value |

## Requirements

For the full `audio_summary` pipeline, `solus` expects these tools to already be installed:

- `yt-dlp`
- `ffmpeg`
- `whisper.cpp` (`whisper-cli` + model file)
- `ollama` with a local model

## Install

```bash
pip install -e .

# Optional extras
pip install 'solus[pdf]'     # PDF extraction
pip install 'solus[ocr]'     # Tesseract OCR (also needs system tesseract-ocr)
pip install 'solus[s3]'      # S3 / MinIO input
pip install 'solus[vector]'  # ChromaDB vector store
pip install 'solus[oidc]'    # OIDC JWT auth for the web server

# Development dependencies (pytest, ruff, mypy, pytest-cov)
pip install -e '.[dev]'
```

## First-time Setup

```bash
solus init             # guided setup: create config, scaffold workflow, check Ollama
solus config           # show config.toml and run doctor
solus config edit      # open config.toml in $EDITOR (VISUAL / EDITOR / nano / vi)
```

`solus init` is the recommended first command — it creates `~/.config/solus/config.toml`, scaffolds a starter workflow, checks Ollama, and prints next steps.
You can also edit the config directly in the web UI at `/config` (requires a server restart to take effect).

## Default Paths

- Config: `~/.config/solus/config.toml`
- Workflows: `~/.config/solus/workflows.d/`
- External modules: `~/.config/solus/modules.d/`
- Triggers: `~/.config/solus/triggers.d/`
- Cache/queue: `~/.local/share/solus`

## Security Modes

`solus` supports two security modes via `config.toml`:

```toml
[security]
mode = "trusted"   # or "untrusted"
```

- `trusted`: all modules can run.
- `untrusted`: modules marked `trusted_only` or `network=true` are blocked at validation/runtime.
  External modules in `~/.config/solus/modules.d/` are also disabled in this mode.

`trusted_only` modules (require explicit trust): `output.webhook`, `output.local_db`, `output.vector_store`, `output.email_send`, `output.obsidian_vault`, `output.slack_notify`, `output.vinsium_node`, `input.email_inbox`, `input.s3_watcher`.

Additionally, in `untrusted` mode, network-enabled modules are rejected (for example `input.source_fetch`, `input.webpage_fetch`, `input.rss_feed`, and most `ai.*` modules that call local HTTP APIs).
For URL-based built-ins that still fetch over HTTP outside workflow step execution (for example RSS polling triggers), Solus validates each redirect hop and resolves hostnames to block private/loopback targets.

Step-level `timeout` values are rejected for `trusted_only` and `network` modules to avoid orphaned side effects when cancellation is not guaranteed.

All XML parsing (RSS feeds, Atom feeds) uses `defusedxml` to prevent XML entity expansion attacks (billion laughs, XXE).

## CLI

Solus is **terminal-first**: every capability available in the web UI is also available from the command line. The web UI is a convenience layer over the same operations.

Direct shorthand (defaults to `ui.default_workflow`, which is `webpage_summary` by default):

```bash
solus "https://example.com/article"
solus "https://www.youtube.com/watch?v=VIDEOID" --workflow audio_summary
solus episode123.mp3 --workflow audio_summary --mode tldr
```

Explicit run/workflow usage:

```bash
solus run --workflow audio_summary episode123.mp3 --mode notes
solus run --workflow audio_summary episode123.mp3 --dry-run
```

Workflow management:

```bash
solus workflows list
solus workflows show audio_summary
solus workflows validate audio_summary
solus workflows examples              # print example YAML templates
solus workflows delete my_workflow    # delete a workflow file (--yes to skip prompt)
```

Trigger management:

```bash
solus triggers list
solus triggers show watch_podcasts
solus triggers validate watch_podcasts
solus triggers examples               # print example trigger YAML templates
solus triggers delete watch_podcasts  # delete a trigger file (--yes to skip prompt)
```

Module inspection:

```bash
solus modules list
solus modules inspect llm_prompt
solus modules inspect ai.llm_summarize
```

Configuration:

```bash
solus init                            # guided first-run setup
solus config                          # create/show config.toml and run doctor
solus config edit                     # open config.toml in $EDITOR
solus examples                        # print example workflow YAML templates
```

Queue + worker + UI:

```bash
solus ingest episode1.mp3 episode2.mp3 --workflow audio_summary
solus worker start
solus worker start --workers 4   # parallel workers
solus worker status
solus worker stop
solus log
solus serve
```

Maintenance:

```bash
solus doctor                              # check deps for your workflows (scoped)
solus doctor --all                        # check all dependencies
solus doctor --fix                        # show copy-pasteable fix commands
solus doctor --workflow audio_summary     # check one workflow's deps
solus cleanup --dry-run
solus retry
solus repair
```

## Workflow Model

Built-in workflow definitions are available in code. User workflows are YAML files under `~/.config/solus/workflows.d/` — you can create and edit them directly in any text editor, with the CLI (`solus workflows show/validate/delete/examples`), or from the web UI at `/workflows` and `/workflow/{name}`. A library of ready-to-use templates is available at the web UI `/examples` page or via `solus workflows examples`.

Example workflow:

```yaml
name: audio_summary
description: "Download/transcribe/summarize long-form audio."
steps:
  - name: fetch_source
    type: input.source_fetch
    config: {}
  - name: normalize_audio
    type: transform.audio_normalize
    config: {}
  - name: transcribe
    type: ai.whisper_transcribe
    config: {}
  - name: summarize
    type: ai.llm_summarize
    config:
      mode: full
      format: markdown
```

### Secrets Interpolation

Step `config` values support `${env:VAR_NAME}` to read from environment variables at workflow load time. This works in any string config field:

```yaml
steps:
  - name: notify
    type: output.slack_notify
    config:
      webhook_url: "${env:SLACK_WEBHOOK_URL}"
  - name: send_email
    type: output.email_send
    config:
      smtp_password: "${env:SMTP_PASSWORD}"
      to_addr: "alerts@example.com"
```

By default, missing variables become empty strings and a warning is logged.
Set `strict_env_vars = true` in `[security]` to raise an error instead (recommended for production).

### Conditional Steps (`when:`)

Any step can be conditionally skipped using a `when:` expression evaluated against the current context data using a safe AST evaluator (no `eval()`):

```yaml
steps:
  - name: classify
    type: ai.llm_classify
    config:
      categories: [tech, science, politics]
      input_key: webpage_text
  - name: save
    type: output.file_write
    when: "classification == 'tech'"
    config:
      input_key: classification
```

Supported operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `is`, `is not`, `in`, `not in`, `and`, `or`, `not`.

### Iterative Steps (`foreach:`)

Any step can iterate over a list in context data using `foreach:`. On each iteration, `_item` and `_index` are injected into the context:

```yaml
steps:
  - name: get_feed
    type: input.rss_feed
    config:
      url: "https://feeds.example.com/podcast.rss"
      limit: 5
  - name: summarize_each
    type: ai.llm_prompt
    foreach: feed_items
    config:
      prompt_template: "Summarize this episode: {_item}"
      output_key: episode_summary
```

### Step Timeouts

Any step can have a per-step timeout. If the step takes longer than `timeout` seconds, Solus raises a timeout error and fails the job immediately. Timeouts are best-effort (the running thread cannot be force-killed), so this is a fail-fast guard rather than a hard process kill:

```yaml
steps:
  - name: slow_llm
    type: ai.llm_prompt
    timeout: 60   # seconds
    config:
      prompt_template: "Analyze: {input_text}"
```

Timed-out jobs are moved directly to `dead_letter` (no automatic retry), even if retries are configured.

### Sub-workflow Steps (`type: workflow`)

Compose workflows by calling one as a step in another:

```yaml
steps:
  - name: run_audio_pipeline
    type: workflow
    config:
      name: audio_summary
```

The sub-workflow executes in the same context and its output data is merged back into the parent context.

### Branch Steps (`type: branch`)

Route execution to different workflows based on a context value:

```yaml
steps:
  - name: route_document
    type: branch
    config:
      condition_key: doc_type
      branches:
        report: process_report
        invoice: process_invoice
      default: process_generic
```

The engine looks up `ctx.data[condition_key]`, matches against the `branches` dict, and executes the corresponding workflow. If no match is found, `default` is used. If no default is set and no match exists, a RuntimeError is raised.

### Error Handling (`on_error:`)

Any step can specify an `on_error` workflow to run if the step fails:

```yaml
steps:
  - name: risky_extraction
    type: ai.llm_extract
    on_error: extraction_fallback
    config:
      input_key: raw_text
      fields: [name, date, amount]
```

When the step raises an exception, Solus sets `_error` (the error message) and `_error_step` (the step name) in the context, then executes the named error-handling workflow. If the error workflow succeeds, execution continues to the next step. If it also fails, the original exception is raised. Steps without `on_error` propagate exceptions normally.

### Parallel Foreach

When iterating over a list, set `parallel` in the step config to process items concurrently:

```yaml
steps:
  - name: embed_chunks
    type: ai.embeddings
    foreach: chunks
    config:
      parallel: 4
      input_key: _item
```

When `parallel` is greater than 0, Solus uses a thread pool with that many workers. Results are collected in order and stored in `_foreach_results` (a list of per-iteration context dicts). When `parallel` is 0 or absent, the existing sequential behavior is used.

### Example: Text Cleaning + Sentiment

```yaml
name: webpage_sentiment
description: "Fetch a page, clean it, and analyze sentiment."
steps:
  - name: fetch
    type: input.webpage_fetch
    config: {}
  - name: clean
    type: transform.text_clean
    config:
      input_key: webpage_text
      output_key: cleaned_text
      strip_html: true
      max_chars: 4000
  - name: sentiment
    type: ai.llm_sentiment
    config:
      input_key: cleaned_text
      scale: pos_neg_neu
  - name: notify
    type: output.slack_notify
    config:
      webhook_url: "${env:SLACK_WEBHOOK}"
      message_template: "Sentiment: {sentiment[label]} ({sentiment[score]:.2f})"
```

### Example: Obsidian + Vector Store

```yaml
name: article_index
description: "Fetch, summarize, and store an article."
steps:
  - name: fetch
    type: input.webpage_fetch
    config: {}
  - name: summarize
    type: ai.llm_prompt
    config:
      prompt_template: "Summarize:\n\n{webpage_text}"
      output_key: output_text
  - name: embed
    type: ai.embeddings
    config:
      input_key: output_text
  - name: store_vector
    type: output.vector_store
    config:
      collection: articles
  - name: save_note
    type: output.obsidian_vault
    config:
      vault_path: "~/Documents/Vault"
      folder: "web-articles"
      tags: [ai, imported]
```

### Example: Email-to-Slack Pipeline

```yaml
name: email_digest
description: "Read unread emails and summarize to Slack."
steps:
  - name: fetch_inbox
    type: input.email_inbox
    config:
      host: imap.gmail.com
      username: "${env:GMAIL_USER}"
      password: "${env:GMAIL_APP_PASSWORD}"
      limit: 5
  - name: summarize_each
    type: ai.llm_prompt
    foreach: messages
    config:
      prompt_template: "Summarize this email in 2 sentences:\n\n{_item[body]}"
      output_key: output_text
  - name: notify
    type: output.slack_notify
    config:
      webhook_url: "${env:SLACK_WEBHOOK}"
      input_key: output_text
```

### Example: S3 + PDF Processing

```yaml
name: s3_pdf_summary
description: "List PDFs in S3, download, and summarize."
steps:
  - name: list_files
    type: input.s3_watcher
    config:
      bucket: my-documents
      prefix: reports/
      pattern: "*.pdf"
      aws_access_key_id: "${env:AWS_ACCESS_KEY_ID}"
      aws_secret_access_key: "${env:AWS_SECRET_ACCESS_KEY}"
      limit: 10
  - name: summarize_each
    type: ai.llm_prompt
    foreach: s3_objects
    config:
      prompt_template: "Report URL: {_item[url]}. Write a one-paragraph summary request."
      output_key: output_text
  - name: save
    type: output.file_write
    config:
      input_key: output_text
```

### Example: Cross-Node with Vinsium

Send results from one Solus instance to another (useful for distributed setups):

```yaml
steps:
  - name: process
    type: ai.llm_prompt
    config:
      prompt_template: "Analyze: {input_text}"
      output_key: output_text
  - name: forward
    type: output.vinsium_node
    config:
      node_url: "https://solus.example.com"
      auth_token: "${env:VINSIUM_TOKEN}"
      workflow_name: store_result
```

## Trigger System

Triggers watch a source for new items and automatically enqueue jobs. Triggers are YAML files in `~/.config/solus/triggers.d/` and are loaded by `solus worker start`.

You can manage triggers from the terminal (`solus triggers list/show/validate/delete/examples`) or from the web UI at `/triggers` and `/trigger/{name}`. A set of ready-made templates is at `/examples#triggers` or `solus triggers examples`.

The `daily_briefing_cron` and `email_inbox_monitor` trigger templates default to the source-agnostic `trigger_event_note` workflow so they run safely out of the box. Replace `workflow:` with your production workflow after scaffolding.

**Important:** the running worker thread reads triggers at startup. After adding or editing a trigger file, restart the worker for the change to take effect:

```bash
solus worker stop && solus worker start
```

### Folder Watch

```yaml
name: watch_podcasts
enabled: false
type: folder_watch
workflow: audio_summary
params:
  mode: full
config:
  path: ~/Downloads/podcasts
  pattern: "*.mp3"
  interval: 30        # seconds between polls
```

Symlinks inside the watch directory that resolve to a path **outside** that directory are silently skipped and logged as a warning. Only files that physically reside within the configured `path` are enqueued.

### RSS Poll

```yaml
name: news_feed
enabled: false
type: rss_poll
workflow: webpage_summary
config:
  url: "https://feeds.example.com/news.rss"
  interval: 300       # seconds between polls
```

### Cron

Run a workflow on a schedule using standard 5-field cron expressions, or a simple interval:

```yaml
name: daily_digest
enabled: false
type: cron
workflow: email_digest
config:
  schedule: "0 8 * * *"    # every day at 08:00 UTC
```

```yaml
name: frequent_check
enabled: false
type: cron
workflow: my_workflow
config:
  interval_seconds: 3600   # every hour
```

Supported cron field syntax: `*`, `*/n` (step), `a,b,c` (list), `a-b` (range), and literal values.

### Email Poll

Poll an IMAP inbox and enqueue a job for each new unseen message:

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

`email_poll` now defaults to at-least-once delivery semantics: an email UID is marked seen only after enqueue succeeds. During transient enqueue/storage failures, a message may be retried and enqueued more than once.

### Inbound Webhook

Any running `solus serve` instance accepts `POST /api/trigger/{workflow_name}` to enqueue a job immediately. The JSON body is passed as job params:

```bash
curl -X POST http://localhost:8765/api/trigger/webpage_summary \
  -H "Content-Type: application/json" \
  -d '{"source": "https://example.com/article"}'
# → {"job_id": "abc123", "status": "queued"}
```

`source` must be a scalar (`string`, `number`, `boolean`, or `null`). Objects/arrays are rejected with HTTP 400. If omitted or `null`, Solus uses `webhook://{workflow_name}`.

#### Webhook Signature Verification

When `webhook_secret` is set in `[security]`, Solus requires an HMAC-SHA256 signature on every `POST /api/trigger/{workflow}` request. Include the signature in the `X-Solus-Signature` header:

```bash
SECRET="my-webhook-secret"
BODY='{"source": "https://example.com/article"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/.*= //')
curl -X POST http://localhost:8765/api/trigger/webpage_summary \
  -H "Content-Type: application/json" \
  -H "X-Solus-Signature: sha256=$SIG" \
  -d "$BODY"
```

If the secret is configured but the header is missing, Solus returns HTTP 401. If the signature is invalid, it returns HTTP 403. When no secret is configured, webhooks are accepted without signature checks.

#### Payload Size Limits

Solus enforces per-route payload size limits to prevent abuse:

| Route | Max size |
|-------|----------|
| `POST /api/trigger/{workflow}` | 1 MiB |
| `POST /ingest-file` | 500 MiB |
| All other POST routes | 2 MiB |

Requests exceeding these limits receive HTTP 413.

#### Webhook Rate Limiting

Solus enforces a per-IP sliding-window rate limit on `POST /api/trigger/*`. The default is 60 requests per minute per source IP. Requests that exceed the limit receive HTTP 429.
`webhook_rate_limit` must be an integer `>= 1`; invalid values fail config load.

Tune the limit in `config.toml`:

```toml
[security]
webhook_rate_limit = 120   # Allow 120 requests per minute per IP
```

For memory safety, Solus keeps this rate-limit state bounded by evicting stale and oldest entries.

#### Outbound Webhook/Slack Logging

`output.webhook` and `output.slack_notify` redact endpoint URLs in logs to `scheme://host` (path/query/token fragments are not logged).

Trigger state (seen files / GUIDs / email UIDs) is tracked per cache directory at `<cache_dir>/triggers/trigger_state.db` (default: `~/.local/share/solus/triggers/trigger_state.db`).

## Job Reliability

### Automatic Retry

Failed jobs are automatically retried with exponential backoff. By default, jobs are retried up to 3 times:

| Attempt | Delay before retry |
|---------|-------------------|
| 1st failure | 30 seconds |
| 2nd failure | 60 seconds |
| 3rd failure | 120 seconds |
| 4th failure | Moved to **dead letter** |

Step timeout failures are not retried; they are moved directly to `dead_letter`.

Jobs in the dead-letter state are visible in the web UI history and in `solus worker status`.

### Step Timing

After each workflow run, `ctx.data["_step_timings"]` contains a list of per-step timing records:

```python
[
  {"name": "fetch", "type": "input.webpage_fetch", "duration_ms": 312, ...},
  {"name": "summarize", "type": "ai.llm_prompt", "duration_ms": 4821, ...},
]
```

## Web UI

Start the web server with `solus serve` (default: `http://localhost:8765`).
If you bind to a non-local interface (for example `--host 0.0.0.0`) without auth enabled, Solus prints a security warning at startup.
For browser-initiated POST routes, Solus enforces same-origin checks (`Sec-Fetch-Site`, `Origin`, `Referer`) to reduce CSRF risk. `/api/trigger/{workflow}` is intentionally exempt for machine-to-machine webhook integrations (including peers on a VPN, such as Vinsium-integrated hosts).
If you expose Solus beyond localhost, enable OIDC auth and treat `/api/trigger/*` as a privileged ingestion endpoint.

Every web UI action has a terminal equivalent — the UI is a convenience layer, not a requirement.

| Route | Terminal equivalent | Description |
|-------|--------------------|----|
| `/` | `solus log` | Main dashboard — job queue, source browser, output viewer |
| `/workflows` | `solus workflows list` | List all workflows |
| `/workflow/{name}` | `solus workflows show/validate NAME` | YAML editor with inline validation and delete |
| `/workflow/new?template=NAME` | `solus workflows examples` | Start a new workflow from a template |
| `/triggers` | `solus triggers list` | List all triggers |
| `/trigger/{name}` | `solus triggers show/validate NAME` | YAML editor for triggers with inline validation and delete |
| `/trigger/new?template=NAME` | `solus triggers examples` | Start a new trigger from a template |
| `/config` | `solus config` / `solus config edit` | View and edit `config.toml` (restart required after save) |
| `/examples` | `solus workflows examples` / `solus triggers examples` | Browse workflow and trigger templates |
| `/modules` | `solus modules list` | Module catalog |
| `/history` | `solus log` | Job run history (paginated, 100/page); bulk "Retry All Failed" and "Clear Dead Letter" toolbar |
| `/events` | — | Server-Sent Events stream (queue counts every 2s) |
| `/healthz` | — | Health check (unauthenticated); returns `{"status":"ok","queue":{...}}` |
| `/api/trigger/{workflow}` | `solus ingest` | `POST` — enqueue a job from an external system |

Pages include an `/events` subscription for live queue signals; currently this updates the pending-job badge automatically.

> **Config changes** take effect after restarting `solus serve`.
> **Trigger changes** take effect after restarting the worker (`solus worker stop && solus worker start`).

### OIDC Authentication

Protect the web UI with an external OIDC provider (Keycloak, Auth0, Dex, etc.):

```toml
[security]
mode = "trusted"
oidc_issuer = "https://keycloak.example.com/realms/myrealm"
oidc_audience = "solus"
oidc_require_auth = true
oidc_allowed_algs = ["RS256", "PS256"]  # optional; defaults to asymmetric algorithms
```

When `oidc_require_auth = true`, all routes except `/healthz` require a valid `Authorization: Bearer <jwt>` header (including `/events` and `POST /api/trigger/*`). Install `pip install 'solus[oidc]'` to enable JWT validation.
`oidc_audience` is required when `oidc_require_auth = true`; Solus fails closed if it is unset.
By default, only asymmetric JWT algorithms are accepted (`RS*`, `PS*`, `ES*`).

## Queue Backend

The job queue is backed by SQLite (`queue/jobs.db` under the cache dir). Existing installations with a `jobs.json` file will be automatically migrated on first startup.

The SQLite backend supports:
- Atomic job claiming via `BEGIN IMMEDIATE` transactions (safe for parallel workers)
- Retry columns (`retry_count`, `max_retries`, `next_retry_at`)
- Dead-letter status for permanently failed jobs
- `solus repair` to recover stuck jobs and reconstruct the queue from filesystem

## Hot Reload

The worker process watches `~/.config/solus/modules.d/`, `~/.config/solus/workflows.d/`, and `~/.config/solus/triggers.d/` for changes every 5 seconds. When a file is added, removed, or modified, modules are automatically re-discovered and re-registered, and triggers are reloaded without restarting the worker.

## External Modules

Drop a `.py` file in `~/.config/solus/modules.d/` to add custom modules. Each file must export a `MODULE` variable of type `ModuleSpec`:

```python
from solus.modules.spec import ModuleSpec, ContextKey

def handle(ctx, step):
    text = ctx.data.get("input_text", "")
    ctx.data["output_text"] = text.upper()
    return ctx

MODULE = ModuleSpec(
    name="uppercase",
    version="0.1.0",
    category="transform",
    description="Convert text to uppercase.",
    handler=handle,
    reads=(ContextKey("input_text", "Text to transform"),),
    writes=(ContextKey("output_text", "Uppercased text"),),
)
```

External modules with the same `step_type` as a built-in module will override the built-in.

## Configuration Reference

`~/.config/solus/config.toml`:

```toml
[paths]
cache_dir = "~/.local/share/solus"

[whisper]
# cli_path = "/usr/local/bin/whisper-cli"
# model_path = "~/.local/share/whisper/ggml-base.en.bin"
threads = 4

[ollama]
base_url = "http://localhost:11434"
model = "qwen3:8b"
# max_transcript_chars = 8000

[yt_dlp]
binary = "yt-dlp"

[ffmpeg]
binary = "ffmpeg"

[workflows]
dir = "~/.config/solus/workflows.d"

[modules]
dir = "~/.config/solus/modules.d"

[triggers]
dir = "~/.config/solus/triggers.d"

[ui]
default_workflow = "webpage_summary"

[security]
mode = "trusted"               # "trusted" | "untrusted"
# webhook_secret = ""          # HMAC-SHA256 secret for /api/trigger/* signature validation
# webhook_rate_limit = 60      # Integer >= 1; max POST /api/trigger/* requests per IP per minute (default 60)
# strict_env_vars = false      # true = raise error on missing ${env:VAR} (recommended for production)
# oidc_issuer = "https://idp.example.com/realms/myrealm"
# oidc_audience = "solus"      # required when oidc_require_auth = true
# oidc_require_auth = false
# oidc_allowed_algs = ["RS256", "PS256"]

[prompts]
# system = "You are a helpful assistant."
# tldr = "Give a 2-3 sentence summary."
```

## Deployment

### Docker

A `Dockerfile` and `docker-compose.yml` are included for containerized deployment.

**Quick start with Docker Compose:**

```bash
docker compose up -d
```

This starts three services:

| Service | Description | Port |
|---------|-------------|------|
| `ollama` | Local LLM server | 11434 |
| `server` | Solus web UI | 8765 |
| `worker` | Background job processor | — |

By default, ports are published on loopback only (`127.0.0.1`) to avoid accidental LAN exposure. The server and worker share config and data volumes. Place your `config.toml` and workflow YAML files in the `solus_config` volume.

If you want to bind-mount local directories instead of named volumes:

```bash
mkdir -p ./my-config ./my-data
SOLUS_CONFIG_MOUNT=./my-config SOLUS_DATA_MOUNT=./my-data docker compose up -d
```

In containers, Solus also honors `OLLAMA_BASE_URL` and `SOLUS_CACHE_DIR` as config defaults when those values are not set in `config.toml`.

If you intentionally expose ports beyond localhost, enable `oidc_require_auth = true` first.

**Build the image standalone:**

```bash
docker build -t solus .
docker run -p 127.0.0.1:8765:8765 -v solus_config:/home/solus/.config/solus solus
```

The image runs as a non-root `solus` user. Override the `CMD` to run the worker instead of the server:

```bash
docker run -v solus_config:/home/solus/.config/solus solus \
  solus worker start --_run-loop --workers 2
```

> **Note:** whisper.cpp is not included in the Docker image. If you need audio transcription, mount the `whisper-cli` binary and model file into the container, or build a custom image.

### systemd

Hardened systemd unit files are provided in `contrib/systemd/`:

```bash
sudo cp contrib/systemd/solus-server.service /etc/systemd/system/
sudo cp contrib/systemd/solus-worker.service /etc/systemd/system/
sudo useradd --system --create-home solus
sudo systemctl daemon-reload
sudo systemctl enable --now solus-server solus-worker
```

The unit files include security hardening (`NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`). Adjust `ReadWritePaths` if your cache or config directories differ from the defaults.

## Development

### Dev dependencies

```bash
pip install -e '.[dev]'
```

This installs `pytest`, `pytest-cov`, `ruff`, `mypy`, and `types-requests`.

### Linting and type checking

```bash
ruff check src/ tests/         # Lint
ruff format --check src/ tests/ # Format check
mypy src/solus/                 # Type check
```

### Running tests

```bash
pytest                                        # Run all tests with coverage
pytest --cov=solus --cov-report=html          # Generate HTML coverage report
```

### CI Pipeline

The GitLab CI pipeline (`.gitlab-ci.yml`) runs:

1. **Lint stage:** `ruff` (check + format) and `mypy`
2. **Test stage:** `pytest` with coverage on Python 3.11, and a compatibility run on Python 3.12

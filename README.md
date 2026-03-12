# Solus

**Self-hosted Zapier for local LLMs** — chain inputs, transforms, and AI steps into automated workflows. Everything runs on your machine.

```bash
pip install solus
solus init
solus https://example.com/any-article
```

That's it. In 60 seconds you go from zero to a working AI pipeline that fetches a webpage, cleans the text, and summarizes it with your local LLM via Ollama.

---

## What is Solus?

Solus is a local-first AI workflow engine that chains **inputs → transforms → local LLM steps → outputs** using simple YAML definitions. Think of it as Zapier or n8n, but designed for local AI inference — no cloud APIs, no vendor lock-in, no data leaving your machine.

You define workflows as YAML files. Each workflow is a pipeline of steps: fetch a webpage, clean the text, summarize with Ollama, write the result to a file or send it to Slack. Solus comes with 30+ built-in modules and you can add your own by dropping a `.py` file into a directory.

Solus is **CLI-first** — every feature is available from the terminal. A web UI is included for convenience but is entirely optional. Workflows can be triggered manually, on a schedule (cron), by watching a folder, polling an RSS feed or email inbox, or via inbound webhooks.

---

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

---

## Feature Highlights

### Built-in Modules (30+)

| Category | Modules |
|----------|---------|
| **Input** | `source_fetch`, `webpage_fetch`, `rss_feed`, `folder_watch`, `parse_pdf`, `email_inbox`, `youtube_playlist`, `s3_watcher` |
| **Transform** | `audio_normalize`, `text_split`, `text_clean`, `metadata_extract`, `ocr` |
| **AI** | `whisper_transcribe`, `llm_summarize`, `llm_prompt`, `llm_classify`, `llm_extract`, `llm_sentiment`, `embeddings` |
| **Output** | `file_write`, `webhook`, `local_db`, `vector_store`, `email_send`, `obsidian_vault`, `slack_notify`, `solus_node` |
| **Meta** | `workflow` (sub-workflows), `branch` (conditional routing) |

### Workflow Features

| Feature | Description |
|---------|-------------|
| Conditional steps | `when:` expressions with safe AST evaluation |
| Iteration | `foreach:` with optional `parallel` concurrency |
| Sub-workflows | Compose workflows by calling one inside another |
| Branching | Route to different workflows based on context values |
| Error handling | `on_error:` fallback workflows per step |
| Step timeouts | Per-step timeout guards with dead-letter on expiry |
| Secrets | `${env:VAR_NAME}` interpolation in any config field |

### Trigger Types (5)

| Trigger | Description |
|---------|-------------|
| Folder watch | Enqueue new files matching a glob pattern |
| RSS poll | Enqueue new feed items on an interval |
| Cron | Standard 5-field cron expressions or simple intervals |
| Email poll | IMAP inbox polling with at-least-once delivery |
| Inbound webhooks | `POST /api/trigger/{workflow}` with HMAC verification and rate limiting |

---

## Example Workflow

```yaml
name: webpage_sentiment
description: "Fetch a page, clean it, and analyze sentiment."
steps:
  - name: fetch
    type: input.webpage_fetch         # fetch and extract text from URL
    config: {}

  - name: clean
    type: transform.text_clean        # strip HTML, normalize whitespace
    config:
      input_key: webpage_text
      output_key: cleaned_text
      strip_html: true
      max_chars: 4000

  - name: sentiment
    type: ai.llm_sentiment            # classify sentiment via Ollama
    config:
      input_key: cleaned_text
      scale: pos_neg_neu

  - name: notify
    type: output.slack_notify          # send result to Slack
    when: "sentiment != 'neutral'"     # conditional: skip if neutral
    config:
      webhook_url: "${env:SLACK_WEBHOOK}"
      message_template: "Sentiment: {sentiment[label]} ({sentiment[score]:.2f})"
```

Save this as `~/.config/solus/workflows.d/webpage_sentiment.yaml` and run:

```bash
solus --workflow webpage_sentiment https://example.com/article
```

---

## CLI Reference

Solus is terminal-first — every web UI action has a CLI equivalent.

```bash
# Run workflows
solus <URL>                              # run default workflow on a URL
solus run --workflow audio_summary ep.mp3 # explicit workflow + source
solus run --dry-run <URL>                # show execution plan without running

# Workflow management
solus workflows list                     # list all workflows
solus workflows show <name>              # print workflow YAML
solus workflows validate <name>          # validate pipeline wiring
solus workflows examples                 # print example YAML templates

# Triggers
solus triggers list | show | validate | examples

# Modules
solus modules list                       # list all discovered modules
solus modules inspect <name>             # show module metadata

# Queue and workers
solus ingest url1 url2 --workflow <name> # queue sources for async processing
solus worker start [--workers 4]         # start background worker(s)
solus worker status                      # show queue counts
solus log                                # monitor queue and worker logs

# Setup and maintenance
solus init                               # guided first-run setup
solus doctor [--fix]                     # check dependencies
solus config [edit]                      # show or edit config.toml
solus serve                              # start web UI (localhost:8765)
solus cleanup --dry-run                  # preview cached artifact removal
solus retry                              # reset failed jobs to pending
solus repair                             # recover stuck jobs from filesystem

# MCP server (AI agent integration)
solus mcp                                # start MCP server over stdio
```

---

## Web UI

Start with `solus serve` (default: `http://localhost:8765`). The web UI provides:

- **Dashboard** — job queue status, source browser, output viewer
- **YAML editors** — create and edit workflows and triggers with inline validation
- **Module catalog** — browse all discovered modules with metadata
- **Job history** — paginated history with bulk retry and dead-letter management
- **Live updates** — SSE-based queue count badges
- **OIDC authentication** — integrate with Keycloak, Auth0, Dex, etc.
- **RBAC** — admin / operator / viewer roles

Every web UI action has a terminal equivalent. The UI is a convenience layer, not a requirement.

---

## Security

### Security Modes

Solus supports `trusted` and `untrusted` modes via `config.toml`:

```toml
[security]
mode = "trusted"   # or "untrusted"
```

- **Trusted**: all modules can run.
- **Untrusted**: modules marked `trusted_only` or `network=true` are blocked. External modules are disabled.

### Additional Security Features

- **OIDC + RBAC** — protect the web UI with external identity providers and role-based access
- **Audit logging** — optional SQLCipher encryption at rest with HMAC chain signing
- **Webhook HMAC** — `X-Solus-Signature` header verification on inbound webhooks
- **Rate limiting** — per-IP sliding window on webhook endpoints (default: 60/min)
- **XML safety** — `defusedxml` for all RSS/Atom parsing (prevents XXE, billion laughs)
- **Secrets interpolation** — `${env:VAR_NAME}` keeps credentials out of YAML files; `strict_env_vars = true` for production

---

## Deployment

### pip (recommended for development)

```bash
pip install solus           # core
pip install 'solus[pdf]'    # + PDF extraction
pip install 'solus[ocr]'    # + Tesseract OCR
pip install 'solus[s3]'     # + S3/MinIO input
pip install 'solus[vector]' # + ChromaDB vector store
pip install 'solus[oidc]'   # + OIDC JWT auth
pip install 'solus[mcp]'    # + MCP server mode
```

### Docker

```bash
docker compose up -d   # starts Ollama + Solus server + worker
```

Services bind to `127.0.0.1` by default. Enable `oidc_require_auth` before exposing ports.

### systemd

Hardened unit files in `contrib/systemd/` with `NoNewPrivileges`, `ProtectSystem=strict`, and `PrivateTmp`.

```bash
sudo cp contrib/systemd/solus-{server,worker}.service /etc/systemd/system/
sudo systemctl enable --now solus-server solus-worker
```

---

## License

Solus is licensed under the **Apache License 2.0**.

See [LICENSE](LICENSE) for full terms.

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

- [GitHub Issues](https://github.com/sfoerster/solus/issues) — bug reports and feature requests
- [GitHub Discussions](https://github.com/sfoerster/solus/discussions) — ideas and use-case proposals
- [Landing page](https://stevenfoerster.com/solus/) — project overview and build logs

### Development

```bash
pip install -e '.[dev]'              # pytest, ruff, mypy
pytest                                # run tests with coverage
ruff check src/ tests/               # lint
mypy src/solus/                      # type check
```

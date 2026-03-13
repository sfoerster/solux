# Solux Roadmap

> Local-first AI workflow engine for local LLMs

This roadmap outlines planned development for Solux, organized into phases. Priorities will shift based on community feedback.

---

## Current State (v0.5.0)

What already exists and works:

- **30 built-in modules** across 5 categories (input, transform, AI, output, meta)
- **YAML-defined workflows** with conditional steps (`when:`), iteration (`foreach:` with parallel), sub-workflows, branching, error handling (`on_error:`), and step timeouts
- **SQLite job queue** with atomic claiming, exponential-backoff retry, and dead-letter
- **5 trigger types:** folder watch, RSS poll, cron, email poll — plus inbound webhooks with HMAC signature verification and rate limiting
- **Web UI** with dashboard, YAML editors, module catalog, job history, SSE live updates
- **OIDC authentication** and **RBAC** (admin / operator / viewer)
- **Audit logging** with optional SQLCipher encryption at rest and HMAC chain signing
- **Security modes** (trusted / untrusted) with network and trust-level enforcement
- **Docker Compose** + hardened **systemd** units
- **Hot reload** for modules, workflows, and triggers
- **External module system** (drop `.py` files in `modules.d/`)
- **CLI-first** — every web UI action has a terminal equivalent
- **MCP server mode** — expose workflows as tools for AI agents

---

## Phase 1 — 60-Second Onboarding

**Goal:** Make Solux genuinely useful on a cold install — from `pip install` to running a real workflow in under 60 seconds.

### 1.1 `solux init` Command

- [x] Add `solux init` command that does everything a first-time user needs in one shot:
  1. Create `~/.config/solux/config.toml` with auto-discovered defaults (Ollama URL, model, binary paths)
  2. Check if Ollama is reachable — if not, print clear install instructions for the user's platform
  3. Check if a default model is available — if not, offer the pull command (`ollama pull qwen3:8b`)
  4. Scaffold a starter workflow file in `workflows.d/`
  5. Run `solux doctor --workflow webpage_summary` to validate the light path
  6. Print a "next steps" block with the exact command to run their first workflow
- [x] `solux init` should be idempotent — safe to re-run without clobbering existing config
- [x] Ensure `solux init` completes in under 10 seconds (no network calls beyond an Ollama ping)

### 1.2 Fix the Default Path

- [x] Change `ui.default_workflow` from `audio_summary` to `webpage_summary` — the audio stack (yt-dlp + ffmpeg + whisper.cpp) is a 20-minute setup, not a 60-second one. `webpage_summary` only needs Ollama.
- [x] Make the bare `solux <URL>` shorthand use `webpage_summary` so that `solux https://example.com` just works after init
- [x] Keep `audio_summary` as a built-in but position it as the "next step" after the user has the basics working

### 1.3 Doctor & Diagnostics Polish

- [x] Improve `solux doctor` output for first-time users: when a check fails, print the **exact next command** to run, not just "not found"
- [x] Add a `--fix` hint mode: for each failing check, show a copy-pasteable fix (e.g., `pip install yt-dlp`, `ollama pull qwen3:8b`, `brew install ffmpeg`)
- [x] Scope doctor output by default — only warn about missing dependencies for workflows the user actually has, not the full audio stack
- [x] Color and formatting pass: green checkmarks, red X's, yellow warnings — make the output scannable at a glance

### 1.4 CLI Polish

- [x] `solux run --dry-run` output polish — show the full execution plan visually (step names, types, arrows between them) so users understand what will happen before it runs
- [x] Add `solux examples` shorthand (alias for `solux workflows examples`)
- [x] Improve `solux run` output — show step progress inline (step 1/3, 2/3, 3/3) with timing, not just a final dump
- [x] Ensure all error messages on the happy path include actionable guidance (e.g., "Ollama not reachable — is it running? Start it with: `ollama serve`")

### 1.5 Validate the 60-Second Claim

- [x] Write an end-to-end smoke test script that times the full path: `pip install -e .` → `solux init` → `solux run --workflow webpage_summary <URL>` — assert it completes in under 60 seconds on a machine with Ollama already running
- [x] Test on a clean environment (fresh venv, no prior config) to catch any assumptions
- [x] Document the minimum viable setup: Python 3.11+, Ollama with any model, `pip install solux`, `solux init`, go (see `docs/QUICK_START.md`)

---

## Phase 2 — Public Launch

**Goal:** Ship Solux to GitHub. Package it for easy installation.

### 2.1 License & Packaging

- [x] Choose license (Apache 2.0)
- [x] Replace the current proprietary license file
- [ ] Publish to PyPI: `pip install solux` and `pipx install solux`

### 2.2 README & First Impressions

- [x] Rewrite README for a public audience — clear value prop, architecture diagram, "try it in 60 seconds" section
- [x] Add CHANGELOG.md
- [x] Clean up any Vinsium-specific references in user-facing docs (the `output.vinsium_node` module stays, but framing shifts to "remote Solux node")

### 2.3 Branding & Landing Page

- [ ] Solux logo and visual identity
- [x] Landing page on sfsite
- [x] Link from README → landing page, landing page → GitHub

### 2.4 Repository & CI

- [ ] Set up GitHub Actions CI (lint, type check, test matrix on 3.11 + 3.12+)
- [ ] Add issue templates (bug report, feature request) and PR template
- [ ] Branch protection on `main` (require CI pass, require review)
- [x] `CODEOWNERS` for the public repo
- [ ] Dependabot or Renovate for dependency updates

### 2.5 Distribution & Launch

- [x] Push to GitHub (public repo)
- [ ] Write deep-dive posts showing real workflows
- [ ] Set up GitHub Discussions for community support

### 2.6 MCP Server Mode

- [x] **MCP server mode** — expose Solux workflows as MCP tools so AI agents (Claude Code, Cursor, Windsurf, etc.) can discover and invoke workflows directly
- [x] Ship as a built-in: `solux mcp` starts the MCP server over stdio
- [x] Custom workflow parameters (`params:`) — workflows declare typed parameters in YAML; MCP tools register with matching signatures
- [ ] Publish to MCP registries / awesome-mcp lists alongside the GitHub launch

---

## Phase 3 — Community & Ecosystem

**Goal:** Build a module ecosystem. Establish Solux as the default tool for local AI automation.

### 3.1 Module Expansion

New built-in modules based on community demand (candidates):

- [ ] `input.mqtt` — subscribe to MQTT topics (IoT / home automation)
- [ ] `input.database_query` — poll a SQL database for new rows
- [ ] `transform.jinja_template` — render Jinja2 templates against context
- [ ] `transform.json_path` — extract fields from JSON using JSONPath
- [ ] `ai.llm_translate` — translate text between languages via local LLM
- [ ] `ai.llm_code` — code generation / transformation via local LLM
- [ ] `ai.vision` — image description / analysis via multimodal local models
- [ ] `output.markdown_report` — generate formatted Markdown reports from context data
- [ ] `output.csv_write` — append structured data to CSV files
- [ ] `output.ntfy` — push notifications via ntfy.sh (self-hosted or public)
- [ ] `output.matrix` — send messages to Matrix rooms

### 3.2 Developer Experience

- [ ] **Workflow debugger** — step-through mode: pause after each step, inspect context, resume or re-run
- [ ] **`solux dev`** — watch a workflow YAML file, re-run on save (hot dev loop)
- [ ] **Template variables** — workflow-level `vars:` block for reusable values across steps
- [ ] **Module scaffold CLI** — `solux modules new my_module` generates a skeleton `.py` file with correct `ModuleSpec` boilerplate
- [ ] **Better error messages** — surface the exact YAML line and config key when validation fails

### 3.3 Community Module Registry

- [ ] Define a community module spec (naming convention, metadata, versioning)
- [ ] `solux modules install <github-url>` — download a module from a Git repo into `modules.d/`
- [ ] **Trust model for community modules** — installed modules run in `untrusted` mode by default (no network, no trusted-only steps). Users must explicitly opt a module into `trusted` mode.
- [ ] Curated list of community modules in the docs

### 3.4 Integration & Interop

- [ ] **REST API completeness** — expose all CLI operations as API endpoints (currently partial)
- [ ] **OpenAPI spec** — auto-generated from the serve routes
- [ ] **n8n / Node-RED nodes** — bridge modules for users already in those ecosystems

### 3.5 External Service MCP Bridge

Enable external service data to be queried through Solux's MCP server mode. Any service that exports structured JSON (or exposes a REST API) can be bridged into MCP tools for AI agents like Claude Code, Codex, or Cursor.

**Architecture:** An external service exports structured data (JSON file or REST API). A Solux workflow or external module reads it. `solux mcp` exposes the workflow as callable tools. AI agents connect to Solux's MCP server.

```
AI agent  →  Solux MCP server  →  JSON file export (any service)
                               →  REST API (any service)
```

#### Core Modules

- [ ] **`input.json_import` module** — Read a structured JSON file from a configurable path, validate against an expected schema version field, and load contents into workflow context. Generic — not tied to any specific service.
  - Config: `path` (file path, supports `${env:VAR}` interpolation), `schema_version` (expected version string, fail if mismatch), `encoding` (default utf-8)
  - Output: full parsed JSON in workflow context under `data` key
- [ ] **`input.rest_api` module** — Fetch JSON from an authenticated REST endpoint. Supports bearer token auth, configurable headers, and response schema validation.
  - Config: `url`, `method` (default GET), `headers` (dict, supports `${env:VAR}`), `auth` (bearer token or none), `schema_version` (optional validation), `timeout` (default 30s)
  - Output: parsed JSON response in workflow context under `data` key

#### MCP Workflow-as-Tool Pattern

- [ ] **Pattern documentation** — Document and provide examples for wrapping a Solux workflow as a set of MCP tools with typed parameters. The workflow defines what data to read and how to query it; `solux mcp` exposes it.
- [x] **Example external modules and workflows** — Shipped in the separate `solux-examples` repo (not core built-ins). First example: `linkedin-engagement/` — reads a JSON export, filters/ranks authors, and exposes 6 MCP tools. Demonstrates the full pattern of external module + custom-param workflows.
- [ ] Additional examples: REST API with auth, cron-triggered scheduled workflows.

### 3.6 Usage Telemetry (opt-in)

- [ ] Opt-in, privacy-respecting telemetry: anonymous aggregate counts (module invocations, workflow success/failure rates, step durations) — no workflow content, no source data, no PII
- [ ] `config.toml` gets a `[telemetry]` section with `enabled = false` by default
- [ ] Transparent data schema published in the docs

---

## Phase 4 — Solux Pro

**Goal:** Launch a paid tier with features for teams and enterprise users.

### 4.1 Pro Feature Set

- [ ] **Shared workflow library** — sync workflows across team members via a central registry (Git-backed or API-synced)
- [ ] **Team RBAC enhancements** — per-workflow and per-trigger permissions (building on the existing admin/operator/viewer roles)
- [ ] **Priority modules** — enterprise connectors:
  - `input.sharepoint` — watch SharePoint document libraries
  - `input.google_drive` — watch Google Drive folders
  - `output.confluence` — write pages to Confluence
  - `output.jira` — create/update Jira issues
  - `output.teams` — Microsoft Teams notifications
  - Healthcare-specific modules (HL7/FHIR connectors, de-identification transforms)
- [ ] **Managed update channel** — signed, pre-tested releases
- [ ] **Audit log export** — scheduled CSV/JSON export, SIEM webhook forwarding
- [ ] **Workflow analytics dashboard** — execution trends, step duration heatmaps, failure rate tracking, module usage stats

---

## Phase 5 — Scale

**Goal:** Expand the product surface for advanced use cases.

### 5.1 Advanced Engine Features

- [ ] **DAG workflows** — directed acyclic graph execution (parallel branches that converge), replacing the current linear-with-branches model
- [ ] **Streaming steps** — stream LLM output through the pipeline instead of waiting for full completion
- [ ] **Multi-model orchestration** — route different steps to different Ollama models (or remote providers as a fallback) within a single workflow
- [ ] **Checkpoint / resume** — save workflow state mid-execution and resume after restart (important for long-running pipelines)
- [ ] **Resource limits** — per-workflow memory and CPU constraints

### 5.2 Deployment Options

- [ ] **Helm chart** for Kubernetes deployment
- [ ] **One-click deploy** templates for Hetzner, DigitalOcean, Railway
- [ ] **ARM builds** — Docker images for Raspberry Pi / ARM servers

### 5.3 Multi-Node

- [ ] **Multi-node workflow coordination** — orchestrate workflows across Solux instances (building on `output.vinsium_node`)
- [ ] **Centralized audit aggregation** — collect audit logs from multiple Solux nodes into a single dashboard
- [ ] **Fleet management API** — deploy workflows and config updates to multiple Solux instances

---

## Non-Goals

Things Solux will **not** become:

- **A cloud service.** Solux is local-first.
- **A visual workflow builder.** The YAML-first approach is the product's identity. The web UI is a convenience layer, not a drag-and-drop canvas.
- **A general-purpose task runner.** Solux is specifically for AI/LLM workflows with local inference. Generic CI/CD or task orchestration (Make, Airflow, Prefect) is out of scope.
- **A replacement for Ollama/whisper.cpp/ffmpeg.** Solux orchestrates these tools; it doesn't reimplement them.

---

## How to Influence This Roadmap

This roadmap is a plan, not a promise. Priorities will shift based on what the community actually needs.

- **GitHub Issues** — feature requests and bug reports
- **GitHub Discussions** — longer-form ideas and use-case proposals
- **sfsite** — build logs and roadmap updates as posts

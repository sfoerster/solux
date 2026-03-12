# Changelog

All notable changes to Solus are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- Custom workflow parameters (`params:`) — workflows can declare typed parameters (str, int, bool) in their YAML. When exposed via `solus mcp`, each workflow registers with its own parameter signature instead of the default 4-param (source, mode, format, model) signature. Backward compatible — workflows without `params:` keep the existing signature.

## [0.5.0] — 2026-03-08 (Phase 1: 60-Second Onboarding)

### Added
- `solus init` command — guided first-run setup with auto-discovery of Ollama, model verification, workflow scaffolding, and doctor validation
- `solus examples` shorthand (alias for `solus workflows examples`)
- `solus run --dry-run` visual execution plan with step names, types, and arrows
- Inline step progress during `solus run` (step 1/3, 2/3, 3/3 with timing)
- `solus doctor --fix` mode with copy-pasteable fix commands for each failing check
- Scoped doctor checks — only warn about dependencies for workflows the user actually has
- Color formatting for doctor output (green checkmarks, red X's, yellow warnings)
- Actionable error messages on the happy path (e.g., "Ollama not reachable — start it with: `ollama serve`")
- Whisper-cli anti-repetition and language configuration options
- End-to-end smoke test validating the 60-second onboarding claim

### Changed
- Default workflow changed from `audio_summary` to `webpage_summary` — only requires Ollama, no ffmpeg/whisper/yt-dlp
- `solus <URL>` shorthand now uses `webpage_summary` by default

### Fixed
- Onboarding review findings (idempotent init, sub-10-second completion)

## [0.4.0] — 2026-03-07 (Test Coverage & Roadmap)

### Added
- 207 new tests covering major coverage gaps across modules, workflows, triggers, and CLI
- Product roadmap (`docs/ROADMAP.md`)

### Fixed
- Removed Vinsium-specific demo tests
- Fixed flaky worker model test

## [0.3.0] — 2026-02-25 (Configuration & Healthcare)

### Added
- Healthcare-specific workflows and tuned prompts
- Branch module for conditional routing to different workflows
- `on_error` handling — per-step fallback workflows
- Parallel `foreach` with configurable thread pool concurrency
- Workflow viewer API endpoint
- Metadata extraction module
- Config and test environment overrides

## [0.2.0] — 2026-02-24 (Job Queue & Web UI)

### Added
- SQLite job queue with atomic claiming, exponential-backoff retry, and dead-letter
- Background worker with parallel worker threads
- SQLCipher encryption at rest for audit logs with HMAC chain signing
- Web UI with dashboard, YAML editors, module catalog, job history, SSE live updates
- OIDC authentication and RBAC (admin / operator / viewer)
- Healthcare example workflows

## [0.1.0] — 2026-02-22 (Core Engine)

### Added
- Initial release of the Solus workflow engine
- 30 built-in modules across 5 categories (input, transform, AI, output, meta)
- YAML-defined workflows with conditional steps, iteration, sub-workflows, and timeouts
- 4 trigger types (folder watch, RSS poll, cron, email poll) plus inbound webhooks
- HMAC signature verification and rate limiting on webhooks
- Security modes (trusted / untrusted) with network and trust-level enforcement
- Hot reload for modules, workflows, and triggers
- External module system (drop `.py` files in `modules.d/`)
- CLI-first architecture — every web UI action has a terminal equivalent
- Docker Compose + hardened systemd units
- Apache 2.0 license

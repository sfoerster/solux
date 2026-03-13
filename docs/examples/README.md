# Solux Example Use Cases

Ready-to-use workflows and triggers covering six common automation scenarios, from simple single-step pipelines to a distributed multi-node AI setup. All processing is local — no cloud API keys required.

---

## Overview

| # | Use Case | Trigger | Key Modules | Extras Required |
|---|----------|---------|-------------|-----------------|
| 1 | [Podcast & YouTube Transcription](#1-podcast--youtube-transcription) | Folder watch | `source_fetch` → `whisper_transcribe` → `llm_summarize` | — |
| 2 | [Morning News Digest](#2-morning-news-digest) | Cron (daily) | `rss_feed` → `llm_prompt` → `slack_notify` | — |
| 3 | [PDF Drop-Folder → Obsidian](#3-pdf-drop-folder--obsidian) | Folder watch | `parse_pdf` → `text_clean` → `llm_summarize` → `obsidian_vault` | `solux[pdf]` |
| 4 | [Email Inbox Triage](#4-email-inbox-triage) | Cron (5 min) | `email_inbox` → `llm_prompt` → `slack_notify` → `local_db` | — |
| 5 | [Research Article Index](#5-research-article-index) | Manual | `webpage_fetch` → `text_split` → `embeddings` → `vector_store` | `solux[vector]` |
| 6 | [Distributed Multi-Node Pipeline](#6-distributed-multi-node-pipeline) | Folder watch + vinsium | `parse_pdf` → `vinsium_node` → `embeddings` → `vector_store` | `solux[pdf]` + `solux[vector]` |

---

## Repository Layout

```
docs/examples/
├── README.md               This file
├── config.toml             Config template — copy to ~/.config/solux/config.toml
├── .env.example            Secrets template  — copy to ~/.config/solux/.env
├── workflows/              Workflow YAML files → ~/.config/solux/workflows.d/
├── triggers/               Trigger YAML files  → ~/.config/solux/triggers.d/
└── modules/                Custom modules      → ~/.config/solux/modules.d/
```

## Setup

### 1. Install Solux and dependencies

```bash
pip install -e .
# Install extras for the use cases you want:
pip install 'solux[pdf]'     # Use cases 3, 6
pip install 'solux[vector]'  # Use cases 5, 6
```

### 2. Configure

```bash
solux config       # Creates ~/.config/solux/config.toml with auto-detected defaults
solux config edit  # Open config.toml in $EDITOR
solux doctor       # Verifies external tools (ffmpeg, whisper-cli, yt-dlp, ollama)
```

Or copy the template from this directory and edit it:

```bash
cp docs/examples/config.toml ~/.config/solux/config.toml
```

Edit `~/.config/solux/config.toml` to set:
- `[whisper] cli_path` and `model_path` if not auto-detected
- `[ollama] model` — default is `qwen3:8b`

You can also view and edit the config from the web UI at `/config` (restart `solux serve` after saving).

### 3. Set secrets

```bash
cp docs/examples/.env.example ~/.config/solux/.env
nano ~/.config/solux/.env    # fill in your values
```

Source the file before starting the worker:

```bash
source ~/.config/solux/.env && solux worker start
```

### 4. Install workflow and trigger files

**Option A — Terminal (copy files directly):**

```bash
cp docs/examples/workflows/*.yaml  ~/.config/solux/workflows.d/
cp docs/examples/triggers/*.yaml   ~/.config/solux/triggers.d/
cp docs/examples/modules/*.py      ~/.config/solux/modules.d/
```

**Option B — Web UI:** Run `solux serve`, navigate to `/examples` to browse built-in templates, or go to `/workflow/new` and `/trigger/new` to create from scratch.

**Tip:** `solux workflows examples` and `solux triggers examples` print starter YAML that you can paste into any editor or copy directly into `~/.config/solux/workflows.d/`.

Verify everything loaded:

```bash
solux workflows list
```

---

## Use Case Details

---

### 1. Podcast & YouTube Transcription

**What it does:** Downloads audio from a YouTube URL, podcast link, or local file. Converts to WAV with ffmpeg, transcribes with whisper.cpp, summarizes with a local Qwen model. Saves output to a markdown file and an Obsidian note.

**Files:**
- `docs/examples/workflows/podcast_summary.yaml`
- `docs/examples/triggers/watch_audio.yaml`
- `docs/examples/triggers/watch_audio_mp4.yaml`

**Environment variables:**
```bash
OBSIDIAN_VAULT_PATH=~/Documents/MyVault
```

**Manual usage:**
```bash
# Summarize a YouTube video
solux run --workflow podcast_summary "https://youtube.com/watch?v=..."

# Summarize a local file in bullet-note mode
solux run --workflow podcast_summary episode.mp3 --mode notes

# Queue a batch
solux ingest ~/Downloads/Podcasts/*.mp3 --workflow podcast_summary
```

**Automatic (trigger):**
```bash
# Start the worker — it picks up triggers automatically
source ~/.config/solux/.env && solux worker start
# Drop any .mp3 or .mp4 into ~/Downloads/Podcasts — processed within 30s
```

**Customization:**
- Change `mode` in the workflow YAML: `full` | `tldr` | `outline` | `notes` | `transcript`
- Change `folder` in the `obsidian_vault` step to file notes elsewhere
- Edit `path` and `pattern` in the trigger files to watch a different directory

---

### 2. Morning News Digest

**What it does:** At 07:00 UTC on weekdays, fetches the latest 15 items from an RSS feed, asks a local LLM to compose a concise briefing, and posts it to Slack. Also saves the briefing to a markdown file.

**Files:**
- `docs/examples/workflows/morning_news_digest.yaml`
- `docs/examples/triggers/morning_digest_cron.yaml`

**Environment variables:**
```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

**Manual usage:**
```bash
# Run the digest now (useful for testing)
solux run --workflow morning_news_digest morning_news_digest
```

**Customization:**
- Edit the `url` in the workflow's `fetch_feed` step to your preferred RSS feed
- Change `schedule` in the trigger YAML (`"0 7 * * 1-5"` = 07:00 UTC weekdays)
- Duplicate the `fetch_feed` + `compose_digest` steps to include multiple feeds

---

### 3. PDF Drop-Folder → Obsidian

**What it does:** Watches `~/Downloads` for new PDF files. For each new PDF: extracts text, cleans it, generates structured bullet notes, extracts metadata (title, authors, date, topic, key claims), and writes a formatted note into your Obsidian vault under `Inbox/PDFs/`.

**Files:**
- `docs/examples/workflows/pdf_to_obsidian.yaml`
- `docs/examples/triggers/watch_pdfs.yaml`

**Environment variables:**
```bash
OBSIDIAN_VAULT_PATH=~/Documents/MyVault
```

**Dependencies:**
```bash
pip install 'solux[pdf]'
```

**Manual usage:**
```bash
solux run --workflow pdf_to_obsidian /path/to/document.pdf
```

**Customization:**
- Change `folder` in the workflow to file notes in a different vault subfolder
- Add `overwrite: true` to re-process already-imported PDFs
- Adjust `max_chars` in `text_clean` for very long documents (default 15000)

---

### 4. Email Inbox Triage

**What it does:** Every 5 minutes, fetches up to 25 unread emails from an IMAP inbox, sends the batch to a local LLM to classify each message by category and priority, posts the triage report to Slack, and archives it in a local SQLite table.

**Files:**
- `docs/examples/workflows/email_triage.yaml`
- `docs/examples/triggers/email_triage_cron.yaml`

**Environment variables:**
```bash
IMAP_HOST=imap.gmail.com
IMAP_USER=you@gmail.com
IMAP_PASSWORD=your-app-password     # Not your account password
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

**Gmail setup:** Enable IMAP in Gmail settings and generate an App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

**Manual usage:**
```bash
solux run --workflow email_triage email_triage
```

**Customization:**
- Edit categories in the `triage_messages` prompt template
- Change `interval_seconds` in the trigger (300 = 5 min, 900 = 15 min)
- Change `folder` from `INBOX` to a specific label/folder
- Set `limit: 0` in the workflow to process all unread messages

---

### 5. Research Article Index

**What it does:** Manually triggered — paste any URL. Fetches the article, cleans the text, splits it into overlapping chunks, embeds each chunk locally via Ollama, and stores them in a ChromaDB collection (`research_corpus`) for semantic search. Also generates a structured summary and files it as an Obsidian note.

**Files:**
- `docs/examples/workflows/article_index.yaml`
- `docs/examples/workflows/chunk_embed_store.yaml` *(sub-workflow)*

**Environment variables:**
```bash
OBSIDIAN_VAULT_PATH=~/Documents/MyVault
```

**Dependencies:**
```bash
pip install 'solux[vector]'
```

**Usage:**
```bash
solux run --workflow article_index "https://example.com/interesting-post"
# Queue multiple articles
solux ingest "https://..." "https://..." --workflow article_index
```

**Querying the vector store** (Python example):
```python
import chromadb
client = chromadb.PersistentClient(path="~/.local/share/solux/chroma")
collection = client.get_collection("research_corpus")
results = collection.query(query_texts=["your search query"], n_results=5)
for doc in results["documents"][0]:
    print(doc[:300])
```

**Technical note:** Embed and store are run together in a sub-workflow (`chunk_embed_store`) called via `foreach`. This ensures each chunk's embedding is paired with the correct chunk text. Two separate `foreach` steps would be out of sync after the first loop completes.

---

### 6. Distributed Multi-Node Pipeline

**What it does:** Splits AI processing across two machines — a lightweight ingestion node (Node A: any machine) and a GPU inference node (Node B: the machine with the fast GPU). Node A watches a folder, extracts PDF text, and forwards it over the local network. Node B chunks, embeds, and stores the text in ChromaDB, and can optionally post the document summary back to Node A.

**Architecture:**
```
Node A (lightweight)              Node B (GPU)
────────────────────              ────────────────────
folder_watch trigger              solux serve (API)
  → ingest_and_forward.yaml  →→→  embed_and_store.yaml
    parse_pdf                       params_loader (custom)
    text_clean                      text_split
    vinsium_node ──────────────→    foreach: embed_one_chunk
                                      ai.embeddings
                                      output.vector_store
                                    ai.llm_summarize
                   ←────────────   output.webhook (optional callback)
```

**Files — Node A:**
- `docs/examples/workflows/ingest_and_forward.yaml`
- `docs/examples/workflows/ingest_done.yaml` *(callback receiver; optional)*
- `docs/examples/triggers/watch_incoming_pdfs.yaml`
- `docs/examples/modules/params_loader.py` *(required for callback receiver)*

**Files — Node B (deploy these on the GPU machine):**
- `docs/examples/workflows/embed_and_store.yaml`
- `docs/examples/workflows/embed_one_chunk.yaml` *(sub-workflow)*
- `docs/examples/modules/params_loader.py` *(custom module)*

**Environment variables:**

*Node A:*
```bash
GPU_NODE_URL=http://192.168.1.50:8765    # IP of the GPU machine
GPU_NODE_TOKEN=                          # Bearer token (if Node B uses OIDC)
```

*Node B:*
```bash
NODE_A_CALLBACK_URL=http://192.168.1.10:8765/api/trigger/ingest_done
# Leave blank to disable callback step automatically
```

**Dependencies:**
```bash
# Node A:
pip install 'solux[pdf]'
# Node B:
pip install 'solux[vector]'
```

**Setup:**

*Node B — start the API server so it can receive forwarded jobs:*
```bash
source ~/.config/solux/.env
solux serve --host 0.0.0.0 --port 8765 &   # Listens on all interfaces
solux worker start --workers 2
```

*Node A — start the worker with triggers:*
```bash
source ~/.config/solux/.env && solux worker start
# Drop a PDF into ~/sync/incoming-pdfs to trigger the pipeline
```

*Node A (optional) — receive callbacks from Node B:*
```bash
source ~/.config/solux/.env
solux serve --host 0.0.0.0 --port 8765
```

**How the text transfer works:**
`output.vinsium_node` on Node A sends the cleaned text as a string in the `text` field of a JSON payload to Node B's `/api/trigger/embed_and_store` endpoint. On Node B, this arrives in `ctx.params["text"]`. The custom `transform.params_loader` module copies it into `ctx.data["cleaned_text"]` so that `transform.text_split` and other modules can access it normally. The same helper module is also used by `ingest_done.yaml` on Node A to read callback payloads from `ctx.params["result"]`.

---

## Trigger: watch_incoming_pdfs.yaml

The trigger file for Use Case 6 is included at `docs/examples/triggers/watch_incoming_pdfs.yaml`.
Edit the `path` to match your actual sync folder before copying it to `triggers.d/`:

```bash
# Edit path, then install:
cp docs/examples/triggers/watch_incoming_pdfs.yaml ~/.config/solux/triggers.d/
mkdir -p ~/sync/incoming-pdfs
```

The worker picks up the new trigger within 5 seconds (hot-reload).

---

## Common Commands

```bash
# Validate a workflow without running it
solux workflows validate podcast_summary

# Inspect a module's inputs/outputs/config
solux modules inspect ai.llm_summarize
solux modules inspect transform.params_loader

# Check what's in the queue
solux worker status

# Retry failed jobs
solux retry

# View live worker logs
solux log --no-history

# Open the web UI
solux serve
```

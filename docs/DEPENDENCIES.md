# Solus Dependencies Guide

Solus runs entirely on your local machine with no cloud API keys. This guide covers installing and configuring the four core external tools—Ollama, whisper.cpp, ffmpeg, and yt-dlp—plus the optional extras for OCR, vector search, S3, and OIDC auth.

After installing everything, run `solus doctor` to verify the setup.

---

## Table of Contents

1. [Quick overview](#quick-overview)
2. [Python](#python)
3. [Ollama (local LLM)](#ollama-local-llm)
4. [whisper.cpp (transcription)](#whispercpp-transcription)
5. [ffmpeg (audio conversion)](#ffmpeg-audio-conversion)
6. [yt-dlp (audio/video download)](#yt-dlp-audiovideo-download)
7. [Optional: Tesseract OCR](#optional-tesseract-ocr)
8. [Optional: ChromaDB (vector store)](#optional-chromadb-vector-store)
9. [Optional: boto3 (S3 / MinIO)](#optional-boto3-s3--minio)
10. [Optional: OIDC auth (web UI)](#optional-oidc-auth-web-ui)
11. [Verifying with `solus doctor`](#verifying-with-solus-doctor)
12. [Troubleshooting](#troubleshooting)

---

## Quick overview

| Dependency | Required for | Install method |
|------------|-------------|----------------|
| Python ≥ 3.11 | Everything | System / pyenv |
| Ollama | All AI/LLM steps | Native package |
| whisper.cpp | Audio transcription | Build from source |
| ffmpeg | Audio normalization | System package |
| yt-dlp | YouTube / podcast download | pip or system |
| tesseract | OCR module (optional) | System package |
| ChromaDB | Vector store (optional) | pip |
| boto3 | S3 / MinIO (optional) | pip |
| PyJWT + cryptography | OIDC web UI auth (optional) | pip |

> **Note:** `defusedxml` is a core Python dependency installed automatically with Solus. It provides safe XML parsing (prevents XXE/billion-laughs attacks) for RSS and Atom feed handling.

---

## Python

Solus requires **Python 3.11 or newer**.

Check your version:

```bash
python3 --version
```

### Install via pyenv (recommended)

[pyenv](https://github.com/pyenv/pyenv) lets you manage multiple Python versions without touching system Python.

```bash
# Install pyenv
curl https://pyenv.run | bash

# Add to your shell (bash example)
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init -)"' >> ~/.bashrc
source ~/.bashrc

# Install Python 3.12
pyenv install 3.12
pyenv global 3.12
```

> **Note:** Solus has built-in pyenv awareness. When it looks up tool binaries (ffmpeg, yt-dlp, etc.) it automatically resolves pyenv shims to their real paths, so you won't run into "shim loop" errors.

### Install Solus itself

```bash
cd /path/to/solus
pip install -e .
```

---

## Ollama (local LLM)

Ollama serves local language models over a simple REST API. Solus uses it for all `ai.llm_*` steps and `ai.embeddings`.

### Install Ollama

**Linux:**

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

This installs the `ollama` binary and registers it as a systemd service.

**macOS:**

Download the app from [ollama.com](https://ollama.com) and drag it to Applications, or install via Homebrew:

```bash
brew install ollama
```

**Windows:**

Download the installer from [ollama.com](https://ollama.com).

### Start Ollama

**Linux (systemd):**

```bash
sudo systemctl enable --now ollama
```

**macOS / manual:**

```bash
ollama serve
```

Ollama listens on `http://localhost:11434` by default.

### Pull a model

Solus defaults to `qwen3:8b`. Pull it before running any AI steps:

```bash
ollama pull qwen3:8b
```

Other good options depending on your hardware:

| Model | VRAM | Notes |
|-------|------|-------|
| `qwen3:8b` | ~6 GB | Good default, fast |
| `qwen3:14b` | ~10 GB | Better reasoning |
| `llama3.2:3b` | ~3 GB | Lightweight, lower quality |
| `mistral:7b` | ~5 GB | Strong general model |
| `nomic-embed-text` | ~1 GB | For `ai.embeddings` steps |

For embeddings (`ai.embeddings` module), you need a dedicated embedding model:

```bash
ollama pull nomic-embed-text
```

List all pulled models:

```bash
ollama list
```

### Configure Solus to use Ollama

In `~/.config/solus/config.toml`:

```toml
[ollama]
base_url = "http://localhost:11434"   # Change if running on another host
model    = "qwen3:8b"                 # Any model you've pulled

# Optional: truncate very long transcripts before sending to the LLM
# max_transcript_chars = 12000
```

To use a non-default model for a single run:

```bash
solus run episode.mp3 --model llama3.2:3b
```

### Running Ollama on a remote machine

If Ollama runs on a different host (e.g., a NAS or GPU server):

```bash
# On the Ollama host, allow remote connections
OLLAMA_HOST=0.0.0.0 ollama serve
```

Then in Solus config:

```toml
[ollama]
base_url = "http://192.168.1.50:11434"
```

---

## whisper.cpp (transcription)

[whisper.cpp](https://github.com/ggerganov/whisper.cpp) is a C++ port of OpenAI Whisper optimized for CPU and Apple Silicon. Solus calls the `whisper-cli` binary it produces.

### Build from source

**Prerequisites:**

```bash
# Debian/Ubuntu
sudo apt install git build-essential cmake

# macOS
xcode-select --install
```

**Clone and build:**

```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
cmake -B build
cmake --build build --config Release -j $(nproc)
```

The binary is at `build/bin/whisper-cli`. You can install it system-wide:

```bash
sudo cp build/bin/whisper-cli /usr/local/bin/
```

Or leave it in place and point Solus at it via config (see below).

**macOS with Metal (GPU acceleration):**

```bash
cmake -B build -DGGML_METAL=ON
cmake --build build --config Release -j $(nproc)
```

**Linux with CUDA:**

```bash
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j $(nproc)
```

### Download a model

Whisper models are distributed as GGML files. Larger models are more accurate but slower.

```bash
cd whisper.cpp

# Small model (fast, decent quality) ~150 MB
bash models/download-ggml-model.sh base.en

# Medium model (recommended) ~500 MB
bash models/download-ggml-model.sh medium.en

# Large model (best quality) ~1.5 GB
bash models/download-ggml-model.sh large-v3
```

Models are saved to `whisper.cpp/models/`. The `.en` variants are English-only and slightly faster; omit `.en` for multilingual support.

Alternatively, download models directly from [Hugging Face](https://huggingface.co/ggerganov/whisper.cpp):

```bash
mkdir -p ~/.local/share/whisper
wget -O ~/.local/share/whisper/ggml-medium.en.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin"
```

### Configure Solus to use whisper.cpp

In `~/.config/solus/config.toml`:

```toml
[whisper]
cli_path   = "/usr/local/bin/whisper-cli"
            # Or: "~/whisper.cpp/build/bin/whisper-cli"
model_path = "~/.local/share/whisper/ggml-medium.en.bin"
            # Or: "~/whisper.cpp/models/ggml-medium.en.bin"
threads    = 4    # Number of CPU threads; default is your CPU core count
```

Solus also checks these fallback locations automatically if `cli_path` is not set:

- `~/src/whisper.cpp/build/bin/whisper-cli`
- `~/whisper.cpp/build/bin/whisper-cli`

And these model fallback locations if `model_path` is not set:

- `~/src/whisper.cpp/models/`
- `~/whisper.cpp/models/`

Model preference order (first found wins): `ggml-medium.bin`, `ggml-base.bin`, `ggml-small.bin`, `ggml-large-v3.bin`, `ggml-large.bin`.

### How Solus calls whisper-cli

For reference, Solus runs:

```
whisper-cli -m <model_path> -f <input.wav> -otxt -of <output_base> -t <threads>
```

The `-otxt` flag writes a `.txt` file alongside the WAV. Solus reads that file as the transcript.

---

## ffmpeg (audio conversion)

ffmpeg normalizes audio to the 16 kHz mono WAV format that whisper.cpp expects.

### Install ffmpeg

**Debian/Ubuntu:**

```bash
sudo apt update && sudo apt install ffmpeg
```

**Fedora/RHEL:**

```bash
sudo dnf install ffmpeg
```

**Arch Linux:**

```bash
sudo pacman -S ffmpeg
```

**macOS:**

```bash
brew install ffmpeg
```

**Windows:**

Download a build from [ffmpeg.org](https://ffmpeg.org/download.html) and add the `bin/` folder to your `PATH`, or install via `winget`:

```bash
winget install ffmpeg
```

Verify installation:

```bash
ffmpeg -version
```

### Configure Solus

By default Solus looks for `ffmpeg` on your `PATH`. If it's installed somewhere unusual:

```toml
[ffmpeg]
binary = "/opt/homebrew/bin/ffmpeg"
```

### How Solus calls ffmpeg

Solus runs:

```
ffmpeg -y -i <input> -ar 16000 -ac 1 -c:a pcm_s16le <output.wav>
```

- `-ar 16000` — Resample to 16 kHz
- `-ac 1` — Downmix to mono
- `-c:a pcm_s16le` — Uncompressed PCM (what whisper.cpp expects)

---

## yt-dlp (audio/video download)

yt-dlp downloads audio from YouTube, podcast feeds, SoundCloud, and hundreds of other sites. Solus uses it in the `input.source_fetch` module.

### Install yt-dlp

**pip (recommended—always up to date):**

```bash
pip install yt-dlp
```

**Homebrew:**

```bash
brew install yt-dlp
```

**Debian/Ubuntu:**

```bash
sudo apt install yt-dlp
```

> **Keep yt-dlp updated.** YouTube regularly changes its site, and old yt-dlp versions break. Update monthly:
>
> ```bash
> pip install --upgrade yt-dlp
> # or
> yt-dlp -U
> ```

Verify installation:

```bash
yt-dlp --version
```

### Configure Solus

By default Solus looks for `yt-dlp` on your `PATH`. Override if needed:

```toml
[yt_dlp]
binary = "/home/user/.local/bin/yt-dlp"
```

### How Solus calls yt-dlp

For single-source audio download:

```
yt-dlp --no-playlist --write-info-json --extract-audio --audio-format mp3 \
       --output "<cache>/audio.%(ext)s" <url>
```

For playlist enumeration (`input.youtube_playlist` module), yt-dlp is called in flat-playlist mode to collect video URLs without downloading.

---

## Optional: Tesseract OCR

Required only for the `transform.ocr` module.

### Install Tesseract

**Debian/Ubuntu:**

```bash
sudo apt install tesseract-ocr
# Additional language packs (example: German)
sudo apt install tesseract-ocr-deu
```

**Fedora:**

```bash
sudo dnf install tesseract
```

**macOS:**

```bash
brew install tesseract
```

**Windows:**

Download the installer from the [UB Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki).

### Install the Python wrapper

```bash
pip install 'solus[ocr]'
# Installs: pytesseract, Pillow
```

### Verify

```bash
tesseract --version
python -c "import pytesseract; print(pytesseract.get_tesseract_version())"
```

### Language codes

Pass the Tesseract language code in your workflow step:

```yaml
- name: read_image
  type: transform.ocr
  config:
    lang: eng       # English (default)
    # lang: deu    # German
    # lang: fra    # French
    # lang: jpn    # Japanese
```

List installed languages:

```bash
tesseract --list-langs
```

---

## Optional: ChromaDB (vector store)

Required only for the `output.vector_store` and `ai.embeddings` → store pipeline.

### Install

```bash
pip install 'solus[vector]'
# Installs: chromadb
```

ChromaDB runs as an embedded library with no separate server needed. Solus stores the database at `~/.local/share/solus/chroma/` by default, configurable per workflow step.

### Embedding model

ChromaDB needs vector embeddings to store and search. Use the `ai.embeddings` module to generate them via Ollama first, then pass the result to `output.vector_store`.

Pull an embedding model:

```bash
ollama pull nomic-embed-text
```

---

## Optional: boto3 (S3 / MinIO)

Required only for the `input.s3_watcher` module.

### Install

```bash
pip install 'solus[s3]'
# Installs: boto3
```

### Configure credentials

Credentials can go in the workflow YAML (via `${env:...}`), or in the standard AWS credentials file:

**~/.aws/credentials:**

```ini
[default]
aws_access_key_id     = AKIAIOSFODNN7EXAMPLE
aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

**For MinIO or other S3-compatible services**, set `endpoint_url` in the workflow step config:

```yaml
- name: list_bucket
  type: input.s3_watcher
  config:
    bucket: my-bucket
    endpoint_url: "http://localhost:9000"
    aws_access_key_id: "${env:MINIO_ACCESS_KEY}"
    aws_secret_access_key: "${env:MINIO_SECRET_KEY}"
```

---

## Optional: OIDC auth (web UI)

Required only if you enable `oidc_require_auth = true` in `config.toml` to protect the Solus web UI with an external identity provider (Keycloak, Auth0, Okta, etc.).

### Install

```bash
pip install 'solus[oidc]'
# Installs: PyJWT, cryptography
```

### Configure

```toml
[security]
oidc_issuer       = "https://keycloak.example.com/realms/myrealm"
oidc_audience     = "solus"
oidc_require_auth = true
oidc_allowed_algs = ["RS256", "PS256"]   # optional
```

Solus fetches the JWKS from `{oidc_issuer}/.well-known/jwks.json` and validates every incoming JWT for signature, expiration, issuer, and audience.
`oidc_audience` is mandatory when `oidc_require_auth = true`; Solus fails closed if it is missing.
By default, only asymmetric JWT algorithms are accepted (`RS*`, `PS*`, `ES*`).

When `oidc_require_auth = true`, callers must include this header on all routes except `/healthz`:

```
Authorization: Bearer <jwt>
```

---

## Verifying with `solus doctor`

After installing everything, run:

```bash
solus doctor
```

`doctor` checks:

| Check | What it does |
|-------|-------------|
| Config file | Found and parseable |
| Cache directory | Exists and writable |
| `yt-dlp` | Binary found; runs `--version` |
| `ffmpeg` | Binary found; runs `-version` |
| `whisper-cli` | Binary found at configured path |
| Whisper model | Model file exists at configured path |
| Ollama API | GET `http://localhost:11434/api/tags` succeeds |
| Ollama model | Configured model is in the pulled-models list |
| Workflows directory | Exists; all YAML files are valid |
| Module dependencies | All `MODULE.dependencies` binary requirements met |

A passing run looks like:

```
✓ Config file found: ~/.config/solus/config.toml
✓ Cache directory: ~/.local/share/solus
✓ yt-dlp: /usr/local/bin/yt-dlp (2024.11.18)
✓ ffmpeg: /usr/bin/ffmpeg (6.1.1)
✓ whisper-cli: /usr/local/bin/whisper-cli
✓ Whisper model: ~/.local/share/whisper/ggml-medium.en.bin
✓ Ollama API: reachable at http://localhost:11434
✓ Ollama model: qwen3:8b available
✓ Workflows: 2 built-in, 3 user-defined
✓ All module dependencies satisfied
```

---

## Troubleshooting

### Ollama

**"connection refused" on port 11434**

Ollama is not running. Start it:

```bash
# macOS / manual Linux
ollama serve

# Linux (systemd)
sudo systemctl start ollama
```

**"model not found"**

The model named in `config.toml` has not been pulled:

```bash
ollama pull qwen3:8b
ollama list    # Confirm it appears
```

**LLM responses are very slow**

- Use a smaller model (`llama3.2:3b` instead of `qwen3:14b`).
- Ensure you're not CPU-bound with a large model. Check `ollama ps` for what's loaded.
- On macOS with Apple Silicon, make sure Ollama is running the Metal-accelerated binary (the official `.app` handles this automatically).
- On Linux with NVIDIA, install the CUDA drivers and the [Ollama CUDA instructions](https://ollama.com/blog/nvidia-gpu).

**Garbled or truncated LLM responses**

Your transcript may exceed `max_transcript_chars`. Set a limit in config:

```toml
[ollama]
max_transcript_chars = 12000
```

---

### whisper.cpp

**"whisper-cli: command not found"**

The binary is not on your `PATH`. Either copy it to `/usr/local/bin/` or set the explicit path:

```toml
[whisper]
cli_path = "/home/user/whisper.cpp/build/bin/whisper-cli"
```

**"model file not found"**

Download a model and set the explicit path:

```toml
[whisper]
model_path = "/home/user/whisper.cpp/models/ggml-medium.en.bin"
```

**Transcription is very slow**

- Increase threads (up to your physical CPU core count):
  ```toml
  [whisper]
  threads = 8
  ```
- Build with hardware acceleration (Metal on macOS, CUDA on Linux).
- Use a smaller model (`base.en` instead of `medium.en`).

**Build fails on Linux**

Ensure `cmake` and a C++17 compiler are installed:

```bash
sudo apt install build-essential cmake
```

---

### ffmpeg

**"ffmpeg: command not found"**

Install via your system package manager (see [Install ffmpeg](#install-ffmpeg) above), or set the binary path explicitly:

```toml
[ffmpeg]
binary = "/opt/homebrew/bin/ffmpeg"
```

**Audio normalization produces silence or errors**

The source file may be corrupt or in an unusual format. Test directly:

```bash
ffmpeg -i your_file.mp3 -ar 16000 -ac 1 -c:a pcm_s16le /tmp/test.wav
ffplay /tmp/test.wav
```

---

### yt-dlp

**"ERROR: Unable to download webpage"**

yt-dlp may be out of date. Update it:

```bash
pip install --upgrade yt-dlp
# or
yt-dlp -U
```

**Download works in terminal but not in Solus**

Solus calls yt-dlp using the binary path from your `PATH` or config. If yt-dlp was installed in a virtual environment or via pyenv, set the path explicitly:

```toml
[yt_dlp]
binary = "/home/user/.local/bin/yt-dlp"
```

**Age-restricted or login-required videos**

yt-dlp supports cookies for authenticated downloads, but Solus does not pass cookie arguments by default. For such content, pre-download the audio manually and pass the file path to Solus instead of a URL.

---

### Tesseract OCR

**"TesseractNotFoundError"**

Tesseract system binary is missing:

```bash
sudo apt install tesseract-ocr    # Debian/Ubuntu
brew install tesseract             # macOS
```

Then verify pytesseract can find it:

```python
import pytesseract
print(pytesseract.get_tesseract_version())
```

**Poor OCR quality**

- Use higher-resolution images (at least 300 DPI).
- Specify the correct language code (`lang: deu` for German, etc.).
- Install language packs: `sudo apt install tesseract-ocr-<lang>`.

---

### pyenv / PATH issues

If `solus doctor` reports a tool as missing but you can run it directly in your terminal, the issue is usually pyenv shim resolution. Solus handles this automatically, but as a fallback set explicit paths in `config.toml`:

```toml
[ffmpeg]
binary = "/home/user/.pyenv/versions/3.12.0/bin/ffmpeg"

[yt_dlp]
binary = "/home/user/.pyenv/versions/3.12.0/bin/yt-dlp"
```

Or install the tools outside of pyenv (system package manager), which avoids shim resolution entirely.

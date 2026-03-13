FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

# yt-dlp: install as a Python package (no system package needed).
RUN pip install --no-cache-dir yt-dlp

# Runtime user — avoid running as root.
RUN useradd --create-home solux
USER solux

ENV SOLUX_CACHE_DIR=/home/solux/.local/share/solux
VOLUME ["/home/solux/.config/solux", "/home/solux/.local/share/solux"]

EXPOSE 8765

# Default: run the web server.  Override CMD to run the worker instead.
CMD ["solux", "serve", "--host", "0.0.0.0", "--port", "8765"]

"""Example/template YAML definitions for workflows and triggers.

These are used by both the CLI (``solux workflows examples``,
``solux triggers examples``) and the web UI Examples page.
"""

from __future__ import annotations

WORKFLOW_EXAMPLES: list[dict] = [
    {
        "name": "audio_summary",
        "title": "Audio Summary",
        "description": (
            "Download audio (YouTube URL, podcast URL, or local file), "
            "transcribe with Whisper, and summarize with Ollama."
        ),
        "yaml": """\
name: audio_summary
description: Download, transcribe, and summarize long-form audio.
steps:
  - name: fetch_source
    type: input.source_fetch
    config: {}
  - name: normalize_audio
    type: transform.audio_normalize
    config: {}
  - name: transcribe
    type: ai.whisper_transcribe
    config:
      output_key: transcript
  - name: summarize
    type: ai.llm_summarize
    config:
      mode: full
      format: markdown
      timestamps: false
""",
    },
    {
        "name": "webpage_summary",
        "title": "Webpage Summary",
        "description": "Fetch a web page and summarize its content with Ollama.",
        "yaml": """\
name: webpage_summary
description: Fetch a webpage and summarize its content.
steps:
  - name: fetch_webpage
    type: input.webpage_fetch
    config: {}
  - name: summarize
    type: ai.llm_summarize
    config:
      input_key: webpage_text
      mode: full
      format: markdown
  - name: write_output
    type: output.file_write
    config: {}
""",
    },
    {
        "name": "transcript_only",
        "title": "Transcript Only",
        "description": (
            "Download and transcribe audio without any LLM summarization. "
            "Good for raw transcripts or when summarization is done separately."
        ),
        "yaml": """\
name: transcript_only
description: Download and transcribe audio without summarization.
steps:
  - name: fetch_source
    type: input.source_fetch
    config: {}
  - name: normalize_audio
    type: transform.audio_normalize
    config: {}
  - name: transcribe
    type: ai.whisper_transcribe
    config:
      output_key: transcript
  - name: write_output
    type: output.file_write
    config:
      input_key: transcript
""",
    },
    {
        "name": "rss_article_summary",
        "title": "RSS Article Summary",
        "description": (
            "Fetch a web article and produce a short summary. Designed to be used with an rss_poll trigger."
        ),
        "yaml": """\
name: rss_article_summary
description: Fetch a web article and summarize it (pair with an rss_poll trigger).
steps:
  - name: fetch_webpage
    type: input.webpage_fetch
    config: {}
  - name: clean_text
    type: transform.text_clean
    config:
      input_key: webpage_text
      output_key: cleaned_text
  - name: summarize
    type: ai.llm_summarize
    config:
      input_key: cleaned_text
      mode: tldr
      format: markdown
  - name: write_output
    type: output.file_write
    config: {}
""",
    },
    {
        "name": "trigger_event_note",
        "title": "Trigger Event Note",
        "description": "Minimal, source-agnostic workflow for trigger smoke tests and scheduling templates.",
        "yaml": """\
name: trigger_event_note
description: Write a simple marker file whenever the workflow is triggered.
steps:
  - name: prepare_output
    type: transform.text_clean
    config:
      input_key: workflow_name
      output_key: output_text
      strip_html: false
  - name: write_output
    type: output.file_write
    config:
      input_key: output_text
      mode: trigger
      format: text
""",
    },
    {
        "name": "audio_sentiment",
        "title": "Audio Sentiment Analysis",
        "description": ("Transcribe audio and then run sentiment analysis on the transcript."),
        "yaml": """\
name: audio_sentiment
description: Transcribe audio and analyse the sentiment of the transcript.
steps:
  - name: fetch_source
    type: input.source_fetch
    config: {}
  - name: normalize_audio
    type: transform.audio_normalize
    config: {}
  - name: transcribe
    type: ai.whisper_transcribe
    config:
      output_key: transcript
  - name: sentiment
    type: ai.llm_sentiment
    config:
      input_key: transcript
      output_key: sentiment_result
  - name: write_output
    type: output.file_write
    config:
      input_key: sentiment_result
""",
    },
]

TRIGGER_EXAMPLES: list[dict] = [
    {
        "name": "watch_podcasts_folder",
        "title": "Watch Folder for Audio Files",
        "description": (
            "Automatically queue any new audio files dropped into a folder. "
            "The worker must be running for files to be processed."
        ),
        "yaml": """\
name: watch_podcasts_folder
enabled: false
type: folder_watch
workflow: audio_summary
params:
  mode: full
  format: markdown
config:
  path: ~/Downloads/podcasts
  pattern: "*.mp3"
  interval: 30
""",
    },
    {
        "name": "rss_podcast_feed",
        "title": "Poll an RSS / Podcast Feed",
        "description": (
            "Check an RSS or podcast feed every hour for new episodes and queue them "
            "automatically for transcription and summarization."
        ),
        "yaml": """\
name: rss_podcast_feed
enabled: false
type: rss_poll
workflow: audio_summary
params:
  mode: full
  format: markdown
config:
  url: https://example.com/feed.xml
  interval: 3600
""",
    },
    {
        "name": "rss_news_digest",
        "title": "Poll a News RSS Feed",
        "description": (
            "Check a news RSS feed and summarize each new article. Pair with the rss_article_summary workflow."
        ),
        "yaml": """\
name: rss_news_digest
enabled: false
type: rss_poll
workflow: rss_article_summary
params: {}
config:
  url: https://example.com/news.rss
  interval: 1800
""",
    },
    {
        "name": "daily_briefing_cron",
        "title": "Daily Cron Trigger",
        "description": (
            "Run a workflow on a fixed schedule using a standard cron expression "
            "(minute hour day-of-month month day-of-week, UTC). "
            "This template defaults to a source-agnostic workflow that always runs."
        ),
        "yaml": """\
name: daily_briefing_cron
enabled: false
type: cron
workflow: trigger_event_note
params: {}
config:
  # Run every day at 07:00 UTC  (min hour dom month dow)
  schedule: "0 7 * * *"
""",
    },
    {
        "name": "email_inbox_monitor",
        "title": "Monitor Email Inbox",
        "description": (
            "Watch an IMAP mailbox for new messages. Use ${env:VAR} to keep credentials out of the config file. "
            "This template defaults to a source-agnostic workflow that always runs."
        ),
        "yaml": """\
name: email_inbox_monitor
enabled: false
type: email_poll
workflow: trigger_event_note
params: {}
config:
  host: imap.example.com
  port: 993
  username: user@example.com
  password: "${env:EMAIL_PASSWORD}"
  folder: INBOX
  interval_seconds: 300
""",
    },
]


def get_workflow_example(name: str) -> dict | None:
    """Return an example dict by name, or None if not found."""
    for ex in WORKFLOW_EXAMPLES:
        if ex["name"] == name:
            return ex
    return None


def get_trigger_example(name: str) -> dict | None:
    """Return a trigger example dict by name, or None if not found."""
    for ex in TRIGGER_EXAMPLES:
        if ex["name"] == name:
            return ex
    return None

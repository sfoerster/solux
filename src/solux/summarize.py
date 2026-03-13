from __future__ import annotations

import json
import re
from typing import Callable

import requests

from .config import Config, PromptsConfig
from .models import FullSummary, OutlineItem, Quote, TLDR, NotesSection
from .prompts import (
    build_full_prompt,
    build_notes_prompt,
    build_outline_prompt,
    build_tldr_prompt,
)


class SummaryError(Exception):
    """Raised when summarization fails."""


def full_summary_to_markdown(summary: FullSummary) -> str:
    lines: list[str] = ["## TL;DR"]
    lines.extend(f"- {item}" for item in summary.tldr.bullets)

    lines.append("\n## Outline")
    for section in summary.outline:
        prefix = f"[{section.start}] " if section.start else ""
        lines.append(f"- {prefix}{section.heading}")
        lines.extend(f"  - {point}" for point in section.points)

    lines.append("\n## Notes")
    lines.append("### Key ideas")
    lines.extend(f"- {item}" for item in summary.notes.key_ideas)
    lines.append("### Memorable quotes")
    for quote in summary.notes.quotes:
        meta = ", ".join(part for part in [quote.speaker, quote.timestamp] if part)
        if meta:
            lines.append(f'- "{quote.text}" ({meta})')
        else:
            lines.append(f'- "{quote.text}"')
    lines.append("### Action items")
    lines.extend(f"- {item}" for item in summary.notes.actions)
    return "\n".join(lines).strip()


def full_summary_to_json(summary: FullSummary) -> str:
    return json.dumps(summary.to_dict(), indent=2, ensure_ascii=False)


def _basic_markdown_to_text(markdown: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", markdown)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s*", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_code_fences(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _split_into_chunks(text: str, max_chars: int, overlap: int = 400) -> list[str]:
    """Split text into chunks of at most max_chars, preferring paragraph/sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    # Clamp overlap so it never prevents forward progress
    effective_overlap = min(overlap, max(0, max_chars - 1))

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end >= len(text):
            chunks.append(text[start:])
            break

        # Try to split on paragraph boundary
        para_split = text.rfind("\n\n", start, end)
        if para_split != -1 and para_split > start:
            split_end = para_split + 2
            chunks.append(text[start:split_end])
            start = max(start + 1, split_end - effective_overlap)
            continue

        # Try to split on sentence boundary (. ! ?)
        sentence_split = -1
        for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
            pos = text.rfind(sep, start, end)
            if pos != -1 and pos + len(sep) - 1 > sentence_split:
                sentence_split = pos + len(sep) - 1
        if sentence_split != -1 and sentence_split > start:
            split_end = sentence_split + 1
            chunks.append(text[start:split_end])
            start = max(start + 1, split_end - effective_overlap)
            continue

        # Hard split
        chunks.append(text[start:end])
        start = max(start + 1, end - effective_overlap)

    return [c for c in chunks if c.strip()]


def _prompt_for_mode(
    mode: str,
    transcript: str,
    timestamps: bool,
    prompts: PromptsConfig | None = None,
) -> dict[str, str]:
    system_override = prompts.system if prompts else None
    if mode == "tldr":
        return build_tldr_prompt(
            transcript,
            instruction_override=prompts.tldr if prompts else None,
            system_override=system_override,
        )
    if mode == "outline":
        return build_outline_prompt(
            transcript,
            timestamps,
            instruction_override=prompts.outline if prompts else None,
            system_override=system_override,
        )
    if mode == "notes":
        return build_notes_prompt(
            transcript,
            timestamps,
            instruction_override=prompts.notes if prompts else None,
            system_override=system_override,
        )
    if mode == "full":
        return build_full_prompt(
            transcript,
            timestamps,
            instruction_override=prompts.full if prompts else None,
            system_override=system_override,
        )
    raise SummaryError(f"Unsupported summarization mode: {mode}")


def call_ollama_chat(
    config: Config,
    prompt: dict[str, str],
    model: str | None = None,
) -> str:
    url = f"{config.ollama.base_url}/api/chat"
    effective_model = model or config.ollama.model
    payload = {
        "model": effective_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"]},
        ],
    }
    try:
        response = requests.post(url, json=payload, timeout=180)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SummaryError(f"Failed to call Ollama API at {url}: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise SummaryError("Ollama returned non-JSON response") from exc

    content = data.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise SummaryError("Ollama response did not include message content")
    return content.strip()


def _chunked_summarize(
    config: Config,
    chunks: list[str],
    mode: str,
    timestamps: bool,
    output_format: str,
    progress: Callable[[str], None] | None,
    model: str | None = None,
) -> str:
    """Summarize each chunk in tldr mode, join results, then summarize in requested mode/format."""
    chunk_summaries: list[str] = []
    total = len(chunks)
    effective_model = model or config.ollama.model
    for i, chunk in enumerate(chunks, 1):
        if progress:
            progress(f"Summarizing chunk {i}/{total} with model '{effective_model}'")
        chunk_prompt = build_tldr_prompt(
            chunk,
            system_override=config.prompts.system if config.prompts else None,
        )
        summary = call_ollama_chat(config, chunk_prompt, model=model)
        chunk_summaries.append(summary)

    meta_transcript = "\n\n".join(chunk_summaries)
    if progress:
        progress(f"Summarizing meta-transcript ({len(meta_transcript)} chars) in mode '{mode}'")
    prompt = _prompt_for_mode(mode, meta_transcript, timestamps, config.prompts)

    if output_format == "json":
        prompt["user"] += (
            "\n\nReturn ONLY valid JSON (no markdown, no prose). Use structured keys appropriate for this mode."
        )

    result = call_ollama_chat(config, prompt, model=model)
    return result


def summarize_transcript(
    config: Config,
    transcript: str,
    mode: str,
    timestamps: bool = False,
    output_format: str = "markdown",
    progress: Callable[[str], None] | None = None,
    model: str | None = None,
) -> str:
    """
    Call Ollama with appropriate prompt for the given mode and return
    the summary as a string in the requested format.
    """
    effective_model = model or config.ollama.model
    max_chars = config.ollama.max_transcript_chars

    if max_chars > 0 and len(transcript) > max_chars:
        chunks = _split_into_chunks(transcript, max_chars)
        if progress:
            progress(
                f"Transcript ({len(transcript)} chars) exceeds max_transcript_chars={max_chars}; "
                f"splitting into {len(chunks)} chunks"
            )
        markdown_result = _chunked_summarize(config, chunks, mode, timestamps, output_format, progress, model=model)
    else:
        prompt = _prompt_for_mode(mode, transcript, timestamps, config.prompts)
        if progress:
            progress(f"Sending transcript to Ollama model '{effective_model}' for mode '{mode}'")

        if output_format == "json":
            prompt["user"] += (
                "\n\nReturn ONLY valid JSON (no markdown, no prose). Use structured keys appropriate for this mode."
            )

        markdown_result = call_ollama_chat(config, prompt, model=model)
        if progress:
            progress("Received response from Ollama")

    if output_format == "markdown":
        return markdown_result

    if output_format == "text":
        return _basic_markdown_to_text(markdown_result)

    if output_format == "json":
        payload_text = _strip_code_fences(markdown_result)
        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise SummaryError("Model output was not valid JSON. Try --format markdown for inspection.") from exc
        return json.dumps(parsed, indent=2, ensure_ascii=False)

    raise SummaryError(f"Unsupported output format: {output_format}")


def parse_full_summary(data: dict) -> FullSummary:
    tldr = TLDR(bullets=list(data.get("tldr", {}).get("bullets", [])))

    outline: list[OutlineItem] = []
    for item in data.get("outline", []):
        outline.append(
            OutlineItem(
                start=item.get("start"),
                heading=item.get("heading", ""),
                points=list(item.get("points", [])),
            )
        )

    quotes: list[Quote] = []
    notes_data = data.get("notes", {})
    for quote in notes_data.get("quotes", []):
        quotes.append(
            Quote(
                text=quote.get("text", ""),
                speaker=quote.get("speaker"),
                timestamp=quote.get("timestamp"),
            )
        )
    notes = NotesSection(
        key_ideas=list(notes_data.get("key_ideas", [])),
        quotes=quotes,
        actions=list(notes_data.get("actions", [])),
    )
    return FullSummary(tldr=tldr, outline=outline, notes=notes)

from __future__ import annotations


SYSTEM_PROMPT = (
    "You are an assistant that turns long-form audio transcripts into accurate, "
    "well-structured notes. Stay faithful to source content and avoid inventing facts."
)


def build_tldr_prompt(
    transcript: str,
    *,
    instruction_override: str | None = None,
    system_override: str | None = None,
) -> dict[str, str]:
    system = system_override if system_override is not None else SYSTEM_PROMPT
    if instruction_override is not None:
        user = f"{instruction_override}\n\nTranscript:\n{transcript}"
    else:
        user = (
            "Create a concise TL;DR of this transcript.\n"
            "- Return 5 to 10 bullet points.\n"
            "- Prioritize key arguments, conclusions, and takeaways.\n\n"
            f"Transcript:\n{transcript}"
        )
    return {"system": system, "user": user}


def build_outline_prompt(
    transcript: str,
    timestamps: bool,
    *,
    instruction_override: str | None = None,
    system_override: str | None = None,
) -> dict[str, str]:
    system = system_override if system_override is not None else SYSTEM_PROMPT
    if instruction_override is not None:
        user = f"{instruction_override}\n\nTranscript:\n{transcript}"
    else:
        timestamp_rule = (
            "Include a timestamp at each top-level heading when visible or inferable."
            if timestamps
            else "Timestamps are optional."
        )
        user = (
            "Create a hierarchical outline for this transcript.\n"
            f"- {timestamp_rule}\n"
            "- Use top-level sections with 2-5 supporting bullets each.\n"
            "- Keep section titles short and descriptive.\n\n"
            f"Transcript:\n{transcript}"
        )
    return {"system": system, "user": user}


def build_notes_prompt(
    transcript: str,
    timestamps: bool,
    *,
    instruction_override: str | None = None,
    system_override: str | None = None,
) -> dict[str, str]:
    system = system_override if system_override is not None else SYSTEM_PROMPT
    if instruction_override is not None:
        user = f"{instruction_override}\n\nTranscript:\n{transcript}"
    else:
        quote_rule = (
            "Add timestamps next to quotes or ideas when available." if timestamps else "Timestamps are optional."
        )
        user = (
            "Create organized notes from this transcript using exactly these sections:\n"
            "1) Key ideas\n2) Memorable quotes\n3) Action items\n"
            f"- {quote_rule}\n"
            "- Keep wording concise and practical.\n\n"
            f"Transcript:\n{transcript}"
        )
    return {"system": system, "user": user}


def build_full_prompt(
    transcript: str,
    timestamps: bool,
    *,
    instruction_override: str | None = None,
    system_override: str | None = None,
) -> dict[str, str]:
    system = system_override if system_override is not None else SYSTEM_PROMPT
    if instruction_override is not None:
        user = f"{instruction_override}\n\nTranscript:\n{transcript}"
    else:
        timestamp_rule = (
            "Add timestamps where they are available from the transcript." if timestamps else "Timestamps are optional."
        )
        user = (
            "Create a complete organized summary in Markdown with the sections:\n"
            "## TL;DR\n## Outline\n## Notes\n"
            "- TL;DR: 5-10 bullets.\n"
            "- Outline: clear sections and supporting bullets.\n"
            "- Notes: Key ideas, Memorable quotes, Action items.\n"
            f"- {timestamp_rule}\n\n"
            f"Transcript:\n{transcript}"
        )
    return {"system": system, "user": user}

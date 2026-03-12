from __future__ import annotations

from solus.workflows.models import Step, Workflow


def webpage_summary_workflow() -> Workflow:
    return Workflow(
        name="webpage_summary",
        description="Fetch a webpage and summarize its content.",
        steps=[
            Step(name="fetch_webpage", type="input.webpage_fetch", config={}),
            Step(
                name="summarize",
                type="ai.llm_summarize",
                config={
                    "input_key": "webpage_text",
                    "mode": "full",
                    "format": "markdown",
                },
            ),
            Step(name="write_output", type="output.file_write", config={}),
        ],
    )


def audio_summary_workflow() -> Workflow:
    return Workflow(
        name="audio_summary",
        description="Download/transcribe/summarize long-form audio.",
        steps=[
            Step(name="fetch_source", type="input.source_fetch", config={}),
            Step(
                name="normalize_audio",
                type="transform.audio_normalize",
                config={},
            ),
            Step(
                name="transcribe",
                type="ai.whisper_transcribe",
                config={"output_key": "transcript"},
            ),
            Step(
                name="summarize",
                type="ai.llm_summarize",
                config={
                    "mode": "full",
                    "format": "markdown",
                    "timestamps": False,
                },
            ),
        ],
    )


BUILTIN_WORKFLOWS: dict[str, Workflow] = {
    "audio_summary": audio_summary_workflow(),
    "webpage_summary": webpage_summary_workflow(),
}

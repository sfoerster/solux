"""Backward-compatibility shim.

The step handler implementations now live in ``solus.modules.<category>.*``.
This module re-exports the handler functions and the legacy
``register_builtin_steps`` helper so that existing imports keep working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from solus.modules._helpers import as_bool as _as_bool  # noqa: F401
from solus.modules._helpers import param as _param  # noqa: F401
from solus.modules._helpers import runtime_flag as _runtime  # noqa: F401
from solus.modules.ai.llm_summarize import handle as step_llm_summarize  # noqa: F401
from solus.modules.ai.whisper_transcribe import handle as step_whisper_transcribe  # noqa: F401
from solus.modules.input.source_fetch import handle as step_source_fetch  # noqa: F401
from solus.modules.transform.audio_normalize import handle as step_audio_normalize  # noqa: F401

if TYPE_CHECKING:
    from solus.workflows.registry import StepRegistry


def register_builtin_steps(registry: StepRegistry) -> None:
    registry.register("source.fetch", step_source_fetch)
    registry.register("audio.normalize", step_audio_normalize)
    registry.register("whisper.transcribe", step_whisper_transcribe)
    registry.register("llm.summarize", step_llm_summarize)

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from solus.config import Config


@dataclass(frozen=True)
class Step:
    name: str
    type: str
    config: dict[str, Any] = field(default_factory=dict)
    when: str | None = None  # Optional expression string for conditional execution
    foreach: str | None = None  # Optional context key holding a list to iterate over
    timeout_seconds: int | None = None  # Optional per-step timeout
    on_error: str | None = None  # Optional workflow name to run on step failure


@dataclass(frozen=True)
class WorkflowParam:
    """Declares a custom parameter for a workflow exposed as an MCP tool."""

    name: str
    type: str = "str"  # str, int, bool
    default: Any = None
    description: str = ""
    required: bool = False


@dataclass(frozen=True)
class Workflow:
    name: str
    description: str
    steps: list[Step]
    params: list[WorkflowParam] = field(default_factory=list)


@dataclass
class Context:
    source: str
    source_id: str
    data: dict[str, Any]
    config: Config
    logger: logging.Logger
    params: dict[str, Any] = field(default_factory=dict)


class ContextKeys:
    """Well-known keys written into ``ctx.data`` by the workflow engine."""

    STEP_TIMINGS = "_step_timings"  # list[dict] — per-step timing records
    FOREACH_ITEM = "_item"  # current item in a foreach iteration
    FOREACH_INDEX = "_index"  # current index in a foreach iteration
    RUNTIME = "runtime"  # dict of runtime flags (no_cache, verbose, etc.)
    FOREACH_RESULTS = "_foreach_results"  # list[dict] — per-iteration results from parallel foreach
    ERROR = "_error"  # str — error message from a failed step (set by on_error)
    ERROR_STEP = "_error_step"  # str — name of the step that failed (set by on_error)

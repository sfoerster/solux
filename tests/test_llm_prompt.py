from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from solus.modules.ai.llm_prompt import handle
from solus.workflows.models import Context, Step


def _make_context(data: dict | None = None, params: dict | None = None) -> Context:
    config = MagicMock()
    return Context(
        source="test",
        source_id="test123",
        data=data or {},
        config=config,
        logger=logging.getLogger("test"),
        params=params or {},
    )


def _make_step(config: dict | None = None) -> Step:
    return Step(name="prompt", type="ai.llm_prompt", config=config or {})


@patch("solus.modules.ai.llm_prompt.call_ollama_chat")
def test_handle_basic_prompt(mock_chat) -> None:
    mock_chat.return_value = "The answer is 42."
    ctx = _make_context(data={"input_text": "What is the meaning of life?"})
    step = _make_step(config={"system_prompt": "You are wise."})

    result = handle(ctx, step)

    mock_chat.assert_called_once()
    call_args = mock_chat.call_args
    prompt = call_args[0][1]
    assert prompt["system"] == "You are wise."
    assert prompt["user"] == "What is the meaning of life?"
    assert result.data["llm_output"] == "The answer is 42."
    assert result.data["output_text"] == "The answer is 42."


@patch("solus.modules.ai.llm_prompt.call_ollama_chat")
def test_handle_template_substitution(mock_chat) -> None:
    mock_chat.return_value = "tech"
    ctx = _make_context(
        data={
            "input_text": "some text",
            "webpage_text": "Article about AI",
            "topic": "technology",
        }
    )
    step = _make_step(
        config={
            "prompt_template": "Classify '{webpage_text}' about {topic}:\n\n{input_text}",
        }
    )

    result = handle(ctx, step)

    call_args = mock_chat.call_args
    prompt = call_args[0][1]
    assert "Article about AI" in prompt["user"]
    assert "technology" in prompt["user"]
    assert "some text" in prompt["user"]


def test_handle_missing_input_key_raises() -> None:
    ctx = _make_context(data={"other_key": "value"})
    step = _make_step()

    with pytest.raises(RuntimeError, match="missing 'input_text'"):
        handle(ctx, step)


def test_handle_missing_template_var_raises() -> None:
    ctx = _make_context(data={"input_text": "hello"})
    step = _make_step(config={"prompt_template": "Process {nonexistent_var}"})

    with pytest.raises(RuntimeError, match="Unresolvable variable"):
        handle(ctx, step)


@patch("solus.modules.ai.llm_prompt.call_ollama_chat")
def test_handle_defaults(mock_chat) -> None:
    mock_chat.return_value = "response"
    ctx = _make_context(data={"input_text": "hello world"})
    step = _make_step()

    result = handle(ctx, step)

    call_args = mock_chat.call_args
    prompt = call_args[0][1]
    assert prompt["system"] == "You are a helpful assistant."
    assert prompt["user"] == "hello world"
    assert result.data["llm_output"] == "response"
    assert result.data["output_text"] == "response"


@patch("solus.modules.ai.llm_prompt.call_ollama_chat")
def test_handle_model_override(mock_chat) -> None:
    mock_chat.return_value = "response"
    ctx = _make_context(
        data={"input_text": "test"},
        params={"model": "llama3:70b"},
    )
    step = _make_step()

    handle(ctx, step)

    call_args = mock_chat.call_args
    assert call_args[1]["model"] == "llama3:70b" or call_args[0][2] == "llama3:70b"

"""Tests for workflow loader edge cases: malformed steps, non-dict documents,
YAML errors, strict secrets, and workflow_to_dict serialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from solux.workflows.loader import (
    WorkflowLoadError,
    _parse_params,
    _parse_step,
    _parse_workflow,
    _load_yaml_file,
    load_workflow,
    list_workflows,
    workflow_to_dict,
)
from solux.workflows.models import Step, Workflow, WorkflowParam


# ---------------------------------------------------------------------------
# _parse_step validation
# ---------------------------------------------------------------------------


class TestParseStep:
    def test_non_dict_step_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[0\\] must be a mapping"):
            _parse_step("not-a-dict", 0)

    def test_missing_name_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[0\\]\\.name must be a non-empty string"):
            _parse_step({"type": "ai.llm_prompt", "config": {}}, 0)

    def test_empty_name_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[0\\]\\.name must be a non-empty string"):
            _parse_step({"name": "  ", "type": "ai.llm_prompt", "config": {}}, 0)

    def test_non_string_name_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[0\\]\\.name must be a non-empty string"):
            _parse_step({"name": 123, "type": "ai.llm_prompt", "config": {}}, 0)

    def test_missing_type_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[0\\]\\.type must be a non-empty string"):
            _parse_step({"name": "step1", "config": {}}, 0)

    def test_non_string_type_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[1\\]\\.type must be a non-empty string"):
            _parse_step({"name": "step1", "type": 42, "config": {}}, 1)

    def test_non_dict_config_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[0\\]\\.config must be a mapping"):
            _parse_step({"name": "step1", "type": "ai.llm_prompt", "config": "not-dict"}, 0)

    def test_non_string_when_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[0\\]\\.when must be a string"):
            _parse_step({"name": "s", "type": "t", "config": {}, "when": 123}, 0)

    def test_non_string_foreach_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="steps\\[0\\]\\.foreach must be a string"):
            _parse_step({"name": "s", "type": "t", "config": {}, "foreach": ["a", "b"]}, 0)

    def test_invalid_timeout_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="timeout must be an integer"):
            _parse_step({"name": "s", "type": "t", "config": {}, "timeout": "fast"}, 0)

    def test_negative_timeout_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="timeout must be a positive integer"):
            _parse_step({"name": "s", "type": "t", "config": {}, "timeout": -5}, 0)

    def test_zero_timeout_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="timeout must be a positive integer"):
            _parse_step({"name": "s", "type": "t", "config": {}, "timeout": 0}, 0)

    def test_non_string_on_error_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="on_error must be a string"):
            _parse_step({"name": "s", "type": "t", "config": {}, "on_error": 42}, 0)

    def test_valid_step_parsed(self) -> None:
        step = _parse_step(
            {"name": " my_step ", "type": " ai.llm_prompt ", "config": {"key": "val"}},
            0,
            interpolate_secrets=False,
        )
        assert step.name == "my_step"
        assert step.type == "ai.llm_prompt"
        assert step.config == {"key": "val"}

    def test_step_with_all_optional_fields(self) -> None:
        step = _parse_step(
            {
                "name": "s",
                "type": "t",
                "config": {},
                "when": " x == 1 ",
                "foreach": " items ",
                "timeout": 60,
                "on_error": " fallback ",
            },
            0,
            interpolate_secrets=False,
        )
        assert step.when == "x == 1"
        assert step.foreach == "items"
        assert step.timeout_seconds == 60
        assert step.on_error == "fallback"

    def test_interpolate_secrets_false(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_SECRET", "s3cret")
        step = _parse_step(
            {"name": "s", "type": "t", "config": {"key": "${env:TEST_SECRET}"}},
            0,
            interpolate_secrets=False,
        )
        assert step.config["key"] == "${env:TEST_SECRET}"

    def test_interpolate_secrets_true(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_SECRET", "s3cret")
        step = _parse_step(
            {"name": "s", "type": "t", "config": {"key": "${env:TEST_SECRET}"}},
            0,
            interpolate_secrets=True,
        )
        assert step.config["key"] == "s3cret"


# ---------------------------------------------------------------------------
# _parse_params validation
# ---------------------------------------------------------------------------


class TestParseParams:
    def test_empty_params_returns_empty_list(self) -> None:
        assert _parse_params([], "test.yaml") == []

    def test_none_params_returns_empty_list(self) -> None:
        assert _parse_params(None, "test.yaml") == []

    def test_non_list_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="'params'.*must be a list"):
            _parse_params("not-a-list", "test.yaml")

    def test_non_dict_entry_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match=r"params\[0\].*must be a mapping"):
            _parse_params(["string"], "test.yaml")

    def test_missing_name_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match=r"params\[0\]\.name.*must be a non-empty string"):
            _parse_params([{"type": "str"}], "test.yaml")

    def test_empty_name_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match=r"params\[0\]\.name.*must be a non-empty string"):
            _parse_params([{"name": "  "}], "test.yaml")

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match=r"params\[0\]\.type.*must be str, int, or bool"):
            _parse_params([{"name": "x", "type": "float"}], "test.yaml")

    def test_valid_param_defaults(self) -> None:
        result = _parse_params([{"name": "count"}], "test.yaml")
        assert result == [WorkflowParam(name="count", type="str", default=None, description="", required=False)]

    def test_valid_param_all_fields(self) -> None:
        result = _parse_params(
            [{"name": "count", "type": "int", "default": 5, "description": "Number of items", "required": True}],
            "test.yaml",
        )
        assert len(result) == 1
        p = result[0]
        assert p.name == "count"
        assert p.type == "int"
        assert p.default == 5
        assert p.description == "Number of items"
        assert p.required is True

    def test_multiple_params(self) -> None:
        result = _parse_params(
            [{"name": "alpha"}, {"name": "beta"}],
            "test.yaml",
        )
        assert len(result) == 2
        assert result[0].name == "alpha"
        assert result[1].name == "beta"

    def test_type_defaults_to_str(self) -> None:
        result = _parse_params([{"name": "x"}], "test.yaml")
        assert result[0].type == "str"


# ---------------------------------------------------------------------------
# _parse_workflow validation
# ---------------------------------------------------------------------------


class TestParseWorkflow:
    def test_non_dict_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="must be a mapping"):
            _parse_workflow("string-doc", source="test.yaml")

    def test_missing_name_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="must include a non-empty 'name'"):
            _parse_workflow(
                {"steps": [{"name": "s", "type": "t", "config": {}}]},
                source="test.yaml",
            )

    def test_non_string_description_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="non-string description"):
            _parse_workflow(
                {"name": "wf", "description": 123, "steps": [{"name": "s", "type": "t", "config": {}}]},
                source="test.yaml",
                interpolate_secrets=False,
            )

    def test_empty_steps_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="non-empty steps list"):
            _parse_workflow(
                {"name": "wf", "steps": []},
                source="test.yaml",
            )

    def test_non_list_steps_raises(self) -> None:
        with pytest.raises(WorkflowLoadError, match="non-empty steps list"):
            _parse_workflow(
                {"name": "wf", "steps": "not-a-list"},
                source="test.yaml",
            )

    def test_valid_workflow(self) -> None:
        wf = _parse_workflow(
            {
                "name": " test_wf ",
                "description": " A test workflow ",
                "steps": [{"name": "s", "type": "t", "config": {}}],
            },
            source="test.yaml",
            interpolate_secrets=False,
        )
        assert wf.name == "test_wf"
        assert wf.description == "A test workflow"
        assert len(wf.steps) == 1

    def test_workflow_with_params(self) -> None:
        wf = _parse_workflow(
            {
                "name": "wf_with_params",
                "description": "Has params",
                "steps": [{"name": "s", "type": "t", "config": {}}],
                "params": [{"name": "count", "type": "int", "default": 5, "description": "Items"}],
            },
            source="test.yaml",
            interpolate_secrets=False,
        )
        assert len(wf.params) == 1
        assert wf.params[0].name == "count"

    def test_workflow_without_params_has_empty_list(self) -> None:
        wf = _parse_workflow(
            {
                "name": "wf_no_params",
                "description": "No params",
                "steps": [{"name": "s", "type": "t", "config": {}}],
            },
            source="test.yaml",
            interpolate_secrets=False,
        )
        assert wf.params == []


# ---------------------------------------------------------------------------
# _load_yaml_file
# ---------------------------------------------------------------------------


class TestLoadYamlFile:
    def test_valid_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "wf.yaml"
        yaml_file.write_text(
            "name: test\ndescription: desc\nsteps:\n  - name: s\n    type: t\n    config: {}\n",
            encoding="utf-8",
        )
        wf = _load_yaml_file(yaml_file, interpolate_secrets=False)
        assert wf.name == "test"

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("{ broken yaml: [", encoding="utf-8")
        with pytest.raises(WorkflowLoadError, match="Invalid YAML"):
            _load_yaml_file(yaml_file)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(WorkflowLoadError, match="Unable to read"):
            _load_yaml_file(tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# list_workflows
# ---------------------------------------------------------------------------


class TestListWorkflows:
    def test_includes_builtins(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows.d"
        wf_dir.mkdir()
        workflows, invalid = list_workflows(workflow_dir=wf_dir)
        # Should include at least audio_summary from builtins
        names = {wf.name for wf in workflows}
        assert "audio_summary" in names
        assert len(invalid) == 0

    def test_invalid_files_reported(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows.d"
        wf_dir.mkdir()
        (wf_dir / "broken.yaml").write_text("not: valid: workflow", encoding="utf-8")
        workflows, invalid = list_workflows(workflow_dir=wf_dir)
        assert len(invalid) >= 1

    def test_user_workflow_overrides_builtin(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows.d"
        wf_dir.mkdir()
        (wf_dir / "audio_summary.yaml").write_text(
            "name: audio_summary\ndescription: custom\nsteps:\n  - name: s\n    type: t\n    config: {}\n",
            encoding="utf-8",
        )
        workflows, _ = list_workflows(workflow_dir=wf_dir, interpolate_secrets=False)
        matching = [wf for wf in workflows if wf.name == "audio_summary"]
        assert len(matching) == 1
        assert matching[0].description == "custom"


# ---------------------------------------------------------------------------
# load_workflow
# ---------------------------------------------------------------------------


class TestLoadWorkflow:
    def test_load_builtin(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "empty-workflows.d"
        wf_dir.mkdir()
        wf = load_workflow("audio_summary", workflow_dir=wf_dir)
        assert wf.name == "audio_summary"

    def test_not_found_raises(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "empty-workflows.d"
        wf_dir.mkdir()
        with pytest.raises(WorkflowLoadError, match="not found"):
            load_workflow("nonexistent", workflow_dir=wf_dir)

    def test_not_found_shows_available(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows.d"
        wf_dir.mkdir()
        with pytest.raises(WorkflowLoadError, match="Available:.*audio_summary"):
            load_workflow("nonexistent", workflow_dir=wf_dir)

    def test_load_by_filename(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows.d"
        wf_dir.mkdir()
        (wf_dir / "custom_wf.yaml").write_text(
            "name: my_custom\ndescription: desc\nsteps:\n  - name: s\n    type: t\n    config: {}\n",
            encoding="utf-8",
        )
        wf = load_workflow("custom_wf", workflow_dir=wf_dir)
        assert wf.name == "my_custom"

    def test_broken_files_counted(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / "workflows.d"
        wf_dir.mkdir()
        (wf_dir / "broken.yaml").write_text("not valid", encoding="utf-8")
        with pytest.raises(WorkflowLoadError, match="Invalid workflow files detected: 1"):
            load_workflow("nonexistent", workflow_dir=wf_dir)


# ---------------------------------------------------------------------------
# workflow_to_dict
# ---------------------------------------------------------------------------


class TestWorkflowToDict:
    def test_basic_serialization(self) -> None:
        wf = Workflow(
            name="test",
            description="desc",
            steps=[Step(name="s", type="t", config={"k": "v"})],
        )
        d = workflow_to_dict(wf)
        assert d["name"] == "test"
        assert d["description"] == "desc"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["config"] == {"k": "v"}

    def test_optional_fields_included(self) -> None:
        wf = Workflow(
            name="test",
            description="",
            steps=[
                Step(
                    name="s",
                    type="t",
                    config={},
                    when="x > 0",
                    foreach="items",
                    timeout_seconds=30,
                    on_error="fallback",
                ),
            ],
        )
        d = workflow_to_dict(wf)
        step = d["steps"][0]
        assert step["when"] == "x > 0"
        assert step["foreach"] == "items"
        assert step["timeout"] == 30
        assert step["on_error"] == "fallback"

    def test_optional_fields_omitted_when_none(self) -> None:
        wf = Workflow(
            name="test",
            description="",
            steps=[Step(name="s", type="t", config={})],
        )
        d = workflow_to_dict(wf)
        step = d["steps"][0]
        assert "when" not in step
        assert "foreach" not in step
        assert "timeout" not in step
        assert "on_error" not in step

    def test_params_serialized(self) -> None:
        wf = Workflow(
            name="test",
            description="desc",
            steps=[Step(name="s", type="t", config={})],
            params=[WorkflowParam(name="count", type="int", default=5, description="Number")],
        )
        d = workflow_to_dict(wf)
        assert "params" in d
        assert len(d["params"]) == 1
        p = d["params"][0]
        assert p["name"] == "count"
        assert p["type"] == "int"
        assert p["default"] == 5
        assert p["description"] == "Number"

    def test_params_omitted_when_empty(self) -> None:
        wf = Workflow(
            name="test",
            description="desc",
            steps=[Step(name="s", type="t", config={})],
        )
        d = workflow_to_dict(wf)
        assert "params" not in d

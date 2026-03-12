"""Tests for Phase 13: Vinsium integration (auth, vinsium_node, secrets)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from solus.workflows.models import Context, Step


def _make_ctx(data: dict | None = None, source: str = "test-source") -> Context:
    from solus.config import (
        BinaryConfig,
        Config,
        OllamaConfig,
        PathsConfig,
        PromptsConfig,
        SecurityConfig,
        WhisperConfig,
    )
    import tempfile

    config = Config(
        paths=PathsConfig(cache_dir=Path(tempfile.mkdtemp())),
        whisper=WhisperConfig(cli_path=None, model_path=None, threads=1),
        ollama=OllamaConfig(base_url="http://localhost:11434", model="test", max_transcript_chars=0),
        yt_dlp=BinaryConfig(binary="yt-dlp"),
        ffmpeg=BinaryConfig(binary="ffmpeg"),
        prompts=PromptsConfig(),
        security=SecurityConfig(),
        config_path=Path("/tmp/test.toml"),
        config_exists=False,
    )
    return Context(
        source=source,
        source_id="test-src-id",
        data=dict(data or {}),
        config=config,
        logger=logging.getLogger("test"),
    )


def _make_step(step_type: str, config: dict | None = None) -> Step:
    return Step(name="test", type=step_type, config=dict(config or {}))


# --- vinsium_node module ---


def test_vinsium_node_module_spec() -> None:
    from solus.modules.output.vinsium_node import MODULE

    assert MODULE.name == "vinsium_node"
    assert MODULE.category == "output"
    assert MODULE.safety == "trusted_only"
    assert MODULE.network is True
    assert any(w.key == "vinsium_response_status" for w in MODULE.writes)
    assert any(w.key == "vinsium_job_id" for w in MODULE.writes)


def test_vinsium_node_missing_url_raises() -> None:
    from solus.modules.output.vinsium_node import handle

    ctx = _make_ctx({"output_text": "hello"})
    step = _make_step("output.vinsium_node")
    with pytest.raises(RuntimeError, match="node_url"):
        handle(ctx, step)


def test_vinsium_node_missing_workflow_raises() -> None:
    from solus.modules.output.vinsium_node import handle

    ctx = _make_ctx({"output_text": "hello"})
    step = _make_step("output.vinsium_node", {"node_url": "https://example.com"})
    with pytest.raises(RuntimeError, match="workflow_name"):
        handle(ctx, step)


def test_vinsium_node_posts_to_endpoint() -> None:
    from solus.modules.output.vinsium_node import handle

    ctx = _make_ctx({"output_text": "Test content"})
    step = _make_step(
        "output.vinsium_node",
        {
            "node_url": "https://vinsium.example.com",
            "workflow_name": "target_workflow",
            "auth_token": "mytoken",
        },
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"job_id": "remote-job-123", "status": "queued"}
    with patch("solus.modules.output.vinsium_node.requests.post", return_value=mock_resp) as mock_post:
        result = handle(ctx, step)
    assert result.data["vinsium_response_status"] == 200
    assert result.data["vinsium_job_id"] == "remote-job-123"
    call_args = mock_post.call_args
    assert "https://vinsium.example.com/api/trigger/target_workflow" in call_args[0][0]
    assert call_args[1]["headers"]["Authorization"] == "Bearer mytoken"


def test_vinsium_node_env_interpolation() -> None:
    import os
    from solus.modules._helpers import interpolate_env

    os.environ["VINSIUM_TOKEN"] = "secret-token"
    result = interpolate_env("${env:VINSIUM_TOKEN}")
    assert result == "secret-token"
    del os.environ["VINSIUM_TOKEN"]


def test_vinsium_node_request_failure_raises() -> None:
    import requests as req
    from solus.modules.output.vinsium_node import handle

    ctx = _make_ctx({"output_text": "hello"})
    step = _make_step(
        "output.vinsium_node",
        {
            "node_url": "https://example.com",
            "workflow_name": "wf",
        },
    )
    with patch(
        "solus.modules.output.vinsium_node.requests.post", side_effect=req.RequestException("Connection refused")
    ):
        with pytest.raises(RuntimeError, match="request"):
            handle(ctx, step)


def test_vinsium_node_custom_input_key() -> None:
    from solus.modules.output.vinsium_node import handle

    ctx = _make_ctx({"my_result": "Custom content"})
    step = _make_step(
        "output.vinsium_node",
        {
            "node_url": "https://example.com",
            "workflow_name": "wf",
            "input_key": "my_result",
        },
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"job_id": "j1"}
    with patch("solus.modules.output.vinsium_node.requests.post", return_value=mock_resp) as mock_post:
        result = handle(ctx, step)
    posted_json = mock_post.call_args[1]["json"]
    assert posted_json["text"] == "Custom content"


def test_vinsium_node_raises_on_non_2xx_by_default() -> None:
    from solus.modules.output.vinsium_node import handle

    ctx = _make_ctx({"output_text": "hello"})
    step = _make_step(
        "output.vinsium_node",
        {
            "node_url": "https://example.com",
            "workflow_name": "wf",
        },
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.ok = False
    mock_resp.text = "bad gateway"
    mock_resp.json.return_value = {}

    with patch("solus.modules.output.vinsium_node.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="server returned 502"):
            handle(ctx, step)


# --- OIDC auth ---


def test_oidc_validator_import() -> None:
    from solus.serve.auth import OIDCValidator, get_validator

    assert OIDCValidator is not None
    assert get_validator is not None


def test_oidc_validator_no_pyjwt() -> None:
    """Should return None when PyJWT not installed."""
    from solus.serve.auth import OIDCValidator
    import sys

    validator = OIDCValidator("https://example.com", "myapp")
    with patch.dict(sys.modules, {"jwt": None, "jwt.PyJWKClient": None}):
        result = validator.validate("fake.token.here")
        assert result is None


def test_oidc_validator_invalid_token() -> None:
    from solus.serve.auth import OIDCValidator

    validator = OIDCValidator("https://example.com", "myapp")
    # Will fail because the token is invalid and issuer doesn't exist
    result = validator.validate("not-a-valid-jwt-token")
    assert result is None


def test_get_validator_caches() -> None:
    from solus.serve.auth import get_validator

    v1 = get_validator("https://example.com", "aud1")
    v2 = get_validator("https://example.com", "aud1")
    assert v1 is v2  # Same instance (cached)


def test_get_validator_different_configs() -> None:
    from solus.serve.auth import get_validator

    v1 = get_validator("https://example1.com", "aud1")
    v2 = get_validator("https://example2.com", "aud1")
    assert v1 is not v2


def test_get_validator_different_algorithms() -> None:
    from solus.serve.auth import get_validator

    v1 = get_validator("https://example.com", "aud", allowed_algorithms=("RS256",))
    v2 = get_validator("https://example.com", "aud", allowed_algorithms=("PS256",))
    assert v1 is not v2


def test_oidc_validator_reuses_jwks_client_instance() -> None:
    from solus.serve.auth import OIDCValidator

    calls = {"init": 0}

    class FakeClient:
        def __init__(self, url: str, cache_keys: bool = True) -> None:
            calls["init"] += 1

        def get_signing_key_from_jwt(self, token: str) -> Any:
            return types.SimpleNamespace(key="secret")

    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWKClient = FakeClient
    fake_jwt.decode = lambda *args, **kwargs: {"sub": "user-1"}

    with patch.dict(sys.modules, {"jwt": fake_jwt}):
        validator = OIDCValidator("https://issuer.example", "aud")
        assert validator.validate("token-one") == {"sub": "user-1"}
        assert validator.validate("token-two") == {"sub": "user-1"}

    assert calls["init"] == 1


def test_oidc_validator_refreshes_jwks_client_after_failure() -> None:
    from solus.serve.auth import OIDCValidator

    state = {"init": 0}

    class FakeClient:
        def __init__(self, url: str, cache_keys: bool = True) -> None:
            state["init"] += 1
            self._id = state["init"]

        def get_signing_key_from_jwt(self, token: str) -> Any:
            if self._id == 1:
                raise RuntimeError("stale key cache")
            return types.SimpleNamespace(key="fresh-secret")

    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWKClient = FakeClient
    fake_jwt.decode = lambda *args, **kwargs: {"sub": "user-2"}

    with patch.dict(sys.modules, {"jwt": fake_jwt}):
        validator = OIDCValidator("https://issuer.example", "aud")
        assert validator.validate("token") == {"sub": "user-2"}

    # First attempt + forced refresh attempt
    assert state["init"] == 2


# --- SecurityConfig OIDC fields ---


def test_security_config_oidc_defaults() -> None:
    from solus.config import SecurityConfig

    sc = SecurityConfig()
    assert sc.oidc_issuer == ""
    assert sc.oidc_audience == ""
    assert sc.oidc_require_auth is False
    assert "RS256" in sc.oidc_allowed_algs


def test_security_config_oidc_fields() -> None:
    from solus.config import SecurityConfig

    sc = SecurityConfig(
        oidc_issuer="https://my-idp.example.com",
        oidc_audience="my-api",
        oidc_require_auth=True,
        oidc_allowed_algs=("RS256", "PS256"),
    )
    assert sc.oidc_issuer == "https://my-idp.example.com"
    assert sc.oidc_audience == "my-api"
    assert sc.oidc_require_auth is True
    assert sc.oidc_allowed_algs == ("RS256", "PS256")


def test_load_config_oidc_fields(tmp_path: Path) -> None:
    from solus.config import load_config

    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[security]\nmode = "trusted"\noidc_issuer = "https://idp.example.com"\n'
        'oidc_audience = "solus"\noidc_require_auth = true\n'
        'oidc_allowed_algs = ["RS256", "PS256"]\n',
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.security.oidc_issuer == "https://idp.example.com"
    assert config.security.oidc_audience == "solus"
    assert config.security.oidc_require_auth is True
    assert config.security.oidc_allowed_algs == ("RS256", "PS256")


def test_load_config_oidc_require_auth_without_audience_fails(tmp_path: Path) -> None:
    from solus.config import ConfigError, load_config

    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[security]\nmode = "trusted"\noidc_issuer = "https://idp.example.com"\noidc_require_auth = true\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="oidc_audience"):
        load_config(config_file)


# --- Auth check in handler ---


def test_handler_check_auth_oidc_required_no_token(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler
    from solus.config import SecurityConfig

    mock_config = MagicMock()
    mock_config.security = SecurityConfig(
        oidc_require_auth=True,
        oidc_issuer="https://idp.example.com",
        oidc_audience="test",
    )
    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=mock_config)
    handler = handler_class.__new__(handler_class)
    # Mock headers without Authorization
    handler.headers = {}
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    result = handler._check_auth()
    assert result is None
    handler.send_response.assert_called_with(401)


def test_handler_check_auth_oidc_required_missing_issuer_fails_closed(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler
    from solus.config import SecurityConfig

    mock_config = MagicMock()
    mock_config.security = SecurityConfig(
        oidc_require_auth=True,
        oidc_issuer="",
        oidc_audience="test",
    )
    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=mock_config)
    handler = handler_class.__new__(handler_class)
    handler.headers = {}
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    result = handler._check_auth()
    assert result is None
    handler.send_response.assert_called_with(500)


def test_handler_check_auth_oidc_required_missing_audience_fails_closed(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler
    from solus.config import SecurityConfig

    mock_config = MagicMock()
    mock_config.security = SecurityConfig(
        oidc_require_auth=True,
        oidc_issuer="https://idp.example.com",
        oidc_audience="",
    )
    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=mock_config)
    handler = handler_class.__new__(handler_class)
    handler.headers = {}
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    result = handler._check_auth()
    assert result is None
    handler.send_response.assert_called_with(500)


def test_handler_check_auth_oidc_required_valid_token(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler
    from solus.config import SecurityConfig
    from solus.serve import auth

    mock_config = MagicMock()
    mock_config.security = SecurityConfig(
        oidc_require_auth=True,
        oidc_issuer="https://idp.example.com",
        oidc_audience="test",
    )
    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=mock_config)
    handler = handler_class.__new__(handler_class)
    handler.headers = {"Authorization": "Bearer valid.token"}
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    mock_validator = MagicMock()
    mock_validator.validate.return_value = {"sub": "user123", "aud": "test"}
    with patch("solus.serve.auth.get_validator", return_value=mock_validator):
        result = handler._check_auth()
    assert result is not None
    assert isinstance(result, dict)
    assert result["sub"] == "user123"


def test_helpers_module_imports_cleanly_in_fresh_process() -> None:
    env = dict(os.environ)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_path}:{existing_pythonpath}" if existing_pythonpath else src_path
    proc = subprocess.run(
        [sys.executable, "-c", "import solus.modules._helpers"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_handler_events_route_requires_auth_when_oidc_enabled(tmp_path: Path) -> None:
    from solus.serve.handler import build_handler
    from solus.config import SecurityConfig

    mock_config = MagicMock()
    mock_config.security = SecurityConfig(
        oidc_require_auth=True,
        oidc_issuer="https://idp.example.com",
        oidc_audience="test",
    )
    handler_class = build_handler(tmp_path, yt_dlp_binary=None, config=mock_config)
    handler = handler_class.__new__(handler_class)
    handler.path = "/events"
    handler.headers = {}
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler._handle_sse = MagicMock()

    handler.do_GET()

    handler._handle_sse.assert_not_called()
    handler.send_response.assert_called_with(401)


# --- Secrets interpolation end-to-end ---


def test_secrets_in_workflow_step_config() -> None:
    """Test that ${env:VAR} is interpolated in step configs during workflow loading."""
    import os
    import yaml
    from solus.workflows.loader import _parse_workflow

    os.environ["TEST_WEBHOOK_URL"] = "https://hooks.slack.com/real-url"
    raw = yaml.safe_load("""
name: test_secrets
description: test
steps:
  - name: notify
    type: output.slack_notify
    config:
      webhook_url: "${env:TEST_WEBHOOK_URL}"
""")
    workflow = _parse_workflow(raw, source="<test>")
    assert workflow.steps[0].config["webhook_url"] == "https://hooks.slack.com/real-url"
    del os.environ["TEST_WEBHOOK_URL"]


def test_secrets_missing_env_in_config() -> None:
    """Missing env vars should become empty strings."""
    import yaml
    from solus.workflows.loader import _parse_workflow

    raw = yaml.safe_load("""
name: test_missing_secret
description: test
steps:
  - name: notify
    type: output.slack_notify
    config:
      webhook_url: "${env:DEFINITELY_NOT_SET_XYZ_12345}"
""")
    workflow = _parse_workflow(raw, source="<test>")
    assert workflow.steps[0].config["webhook_url"] == ""

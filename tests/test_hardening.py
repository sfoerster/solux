"""Tests for security hardening: webhook HMAC, defusedxml, redirect guard,
thread timeout, and payload size limits."""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from solus.serve.api import verify_webhook_signature
from solus.workflows.engine import StepTimeoutError, _run_step_with_optional_timeout
from solus.workflows.models import Context, Step


# ---------------------------------------------------------------------------
# Webhook HMAC signature validation
# ---------------------------------------------------------------------------


class TestWebhookSignature:
    def test_valid_signature(self):
        body = b'{"source": "test"}'
        secret = "mysecret"
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, sig, secret) is True

    def test_invalid_signature(self):
        body = b'{"source": "test"}'
        secret = "mysecret"
        assert verify_webhook_signature(body, "sha256=badbeef", secret) is False

    def test_missing_prefix(self):
        body = b'{"source": "test"}'
        secret = "mysecret"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, sig, secret) is False

    def test_empty_body(self):
        body = b""
        secret = "s"
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, sig, secret) is True

    def test_wrong_secret(self):
        body = b"hello"
        sig = "sha256=" + hmac.new(b"right", body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, sig, "wrong") is False


# ---------------------------------------------------------------------------
# Thread timeout (daemon thread approach)
# ---------------------------------------------------------------------------


class TestStepTimeout:
    def test_fast_function_returns_result(self):
        result = _run_step_with_optional_timeout(
            lambda: 42,
            step_name="fast",
            step_type="test",
            timeout_seconds=5,
        )
        assert result == 42

    def test_no_timeout_returns_result(self):
        result = _run_step_with_optional_timeout(
            lambda: "ok",
            step_name="notimeout",
            step_type="test",
            timeout_seconds=None,
        )
        assert result == "ok"

    def test_slow_function_raises_timeout(self):
        def slow():
            time.sleep(10)
            return "never"

        with pytest.raises(StepTimeoutError, match="timed out after 1s"):
            _run_step_with_optional_timeout(
                slow,
                step_name="slow",
                step_type="test",
                timeout_seconds=1,
            )

    def test_exception_propagated(self):
        def boom():
            raise ValueError("kaboom")

        with pytest.raises(ValueError, match="kaboom"):
            _run_step_with_optional_timeout(
                boom,
                step_name="boom",
                step_type="test",
                timeout_seconds=5,
            )


# ---------------------------------------------------------------------------
# defusedxml: ensure we use SafeET in rss_feed and triggers
# ---------------------------------------------------------------------------


class TestDefusedXml:
    def test_rss_feed_uses_defusedxml(self):
        """Verify rss_feed module imports defusedxml.ElementTree."""
        from solus.modules.input import rss_feed
        import defusedxml.ElementTree as SafeET

        # The module should have SafeET available at module level
        assert hasattr(rss_feed, "SafeET")

    def test_billion_laughs_blocked(self):
        """defusedxml should block entity expansion attacks."""
        import defusedxml.ElementTree as SafeET
        from defusedxml import EntitiesForbidden

        # Classic billion laughs payload
        payload = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;">
]>
<root>&lol2;</root>"""
        with pytest.raises((EntitiesForbidden, ET.ParseError)):
            SafeET.fromstring(payload)


# ---------------------------------------------------------------------------
# Consolidated redirect guard
# ---------------------------------------------------------------------------


class TestRedirectGuard:
    def test_no_redirect(self):
        from solus.modules._helpers import fetch_with_redirect_guard

        mock_resp = MagicMock()
        mock_resp.is_redirect = False
        mock_resp.is_permanent_redirect = False
        mock_resp.raise_for_status = MagicMock()
        with patch("solus.modules._helpers.requests.get", return_value=mock_resp):
            result = fetch_with_redirect_guard("https://example.com", context="test")
        assert result is mock_resp

    def test_too_many_redirects(self):
        from solus.modules._helpers import fetch_with_redirect_guard

        mock_resp = MagicMock()
        mock_resp.is_redirect = True
        mock_resp.is_permanent_redirect = False
        mock_resp.headers = {"Location": "https://example.com/loop"}
        with patch("solus.modules._helpers.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="too many redirects"):
                fetch_with_redirect_guard("https://example.com", context="test")

    def test_single_redirect_followed(self):
        from solus.modules._helpers import fetch_with_redirect_guard

        redirect_resp = MagicMock()
        redirect_resp.is_redirect = True
        redirect_resp.is_permanent_redirect = False
        redirect_resp.headers = {"Location": "https://example.com/final"}

        final_resp = MagicMock()
        final_resp.is_redirect = False
        final_resp.is_permanent_redirect = False
        final_resp.raise_for_status = MagicMock()

        with patch("solus.modules._helpers.requests.get", side_effect=[redirect_resp, final_resp]):
            result = fetch_with_redirect_guard("https://example.com", context="test")
        assert result is final_resp

    def test_block_private_ip(self):
        from solus.modules._helpers import fetch_with_redirect_guard

        with pytest.raises(RuntimeError, match="private or loopback"):
            fetch_with_redirect_guard(
                "http://127.0.0.1/admin",
                context="test",
                block_private=True,
            )


# ---------------------------------------------------------------------------
# Payload size limit on webhook endpoint
# ---------------------------------------------------------------------------


class TestPayloadSizeLimit:
    def test_webhook_max_body_bytes_constant_exists(self):
        from solus.serve.handler import _MAX_UPLOAD_BYTES, _MAX_WEBHOOK_BYTES

        assert _MAX_WEBHOOK_BYTES <= _MAX_UPLOAD_BYTES
        assert _MAX_WEBHOOK_BYTES > 0

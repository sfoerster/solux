"""Tests for _helpers.py: SSRF prevention, env interpolation, URL validation,
redirect guard, and utility functions."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from solus.modules._helpers import (
    _is_private_ip,
    _resolved_ips,
    as_bool,
    fetch_with_redirect_guard,
    interpolate_env,
    param,
    runtime_flag,
    validate_http_url,
)


# ---------------------------------------------------------------------------
# interpolate_env
# ---------------------------------------------------------------------------


class TestInterpolateEnv:
    def test_basic_substitution(self, monkeypatch) -> None:
        monkeypatch.setenv("TEST_VAR", "hello")
        assert interpolate_env("${env:TEST_VAR}") == "hello"

    def test_missing_var_empty_string(self, monkeypatch) -> None:
        monkeypatch.delenv("MISSING_VAR_12345", raising=False)
        result = interpolate_env("prefix-${env:MISSING_VAR_12345}-suffix")
        assert result == "prefix--suffix"

    def test_strict_raises_on_missing(self, monkeypatch) -> None:
        monkeypatch.delenv("STRICT_MISSING_67890", raising=False)
        with pytest.raises(RuntimeError, match="Required environment variable"):
            interpolate_env("${env:STRICT_MISSING_67890}", strict=True)

    def test_no_pattern_passthrough(self) -> None:
        assert interpolate_env("plain text") == "plain text"

    def test_multiple_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("A_VAR", "aaa")
        monkeypatch.setenv("B_VAR", "bbb")
        result = interpolate_env("${env:A_VAR}+${env:B_VAR}")
        assert result == "aaa+bbb"

    def test_warn_missing_false_suppresses_warning(self, monkeypatch, caplog) -> None:
        monkeypatch.delenv("QUIET_MISSING_VAR", raising=False)
        import logging

        with caplog.at_level(logging.WARNING):
            interpolate_env("${env:QUIET_MISSING_VAR}", warn_missing=False)
        assert not any("QUIET_MISSING_VAR" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _is_private_ip
# ---------------------------------------------------------------------------


class TestIsPrivateIp:
    def test_localhost_string(self) -> None:
        assert _is_private_ip("localhost") is True
        assert _is_private_ip("LOCALHOST") is True
        assert _is_private_ip("localhost.localdomain") is True

    def test_loopback_ipv4(self) -> None:
        assert _is_private_ip("127.0.0.1") is True

    def test_private_rfc1918(self) -> None:
        assert _is_private_ip("192.168.1.1") is True
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("172.16.0.1") is True

    def test_link_local(self) -> None:
        assert _is_private_ip("169.254.1.1") is True

    def test_public_ip(self) -> None:
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False

    def test_non_ip_hostname(self) -> None:
        assert _is_private_ip("example.com") is False

    def test_ipv6_loopback(self) -> None:
        assert _is_private_ip("::1") is True


# ---------------------------------------------------------------------------
# _resolved_ips
# ---------------------------------------------------------------------------


class TestResolvedIps:
    def test_resolution_failure_returns_empty(self) -> None:
        import socket

        with patch("solus.modules._helpers.socket.getaddrinfo", side_effect=socket.gaierror("nope")):
            assert _resolved_ips("nonexistent.invalid") == set()

    def test_returns_ip_strings(self) -> None:
        fake_addrinfo = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        with patch("solus.modules._helpers.socket.getaddrinfo", return_value=fake_addrinfo):
            result = _resolved_ips("example.com")
        assert "93.184.216.34" in result

    def test_empty_sockaddr_skipped(self) -> None:
        fake_addrinfo = [
            (2, 1, 6, "", ()),  # empty sockaddr
        ]
        with patch("solus.modules._helpers.socket.getaddrinfo", return_value=fake_addrinfo):
            result = _resolved_ips("example.com")
        assert result == set()


# ---------------------------------------------------------------------------
# validate_http_url
# ---------------------------------------------------------------------------


class TestValidateHttpUrl:
    def test_valid_http(self) -> None:
        validate_http_url("http://example.com")

    def test_valid_https(self) -> None:
        validate_http_url("https://example.com")

    def test_ftp_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="not allowed"):
            validate_http_url("ftp://example.com")

    def test_empty_scheme_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="not allowed"):
            validate_http_url("noscheme.com/path")

    def test_block_private_localhost(self) -> None:
        with pytest.raises(RuntimeError, match="private or loopback"):
            validate_http_url("http://localhost/secret", block_private=True)

    def test_block_private_rfc1918(self) -> None:
        with pytest.raises(RuntimeError, match="private or loopback"):
            validate_http_url("http://192.168.1.1/api", block_private=True)

    def test_block_private_with_resolution(self) -> None:
        with patch("solus.modules._helpers._resolved_ips", return_value={"127.0.0.1"}):
            with pytest.raises(RuntimeError, match="resolved to a private"):
                validate_http_url(
                    "http://sneaky.example.com/api",
                    block_private=True,
                    resolve_hostname=True,
                )

    def test_unresolvable_host_blocked_in_untrusted(self) -> None:
        with patch("solus.modules._helpers._resolved_ips", return_value=set()):
            with pytest.raises(RuntimeError, match="could not be resolved"):
                validate_http_url(
                    "http://ghost.example.com",
                    block_private=True,
                    resolve_hostname=True,
                )

    def test_context_prefix_in_error(self) -> None:
        with pytest.raises(RuntimeError, match="trigger\\[rss\\]"):
            validate_http_url("ftp://bad.com", context="trigger[rss]")


# ---------------------------------------------------------------------------
# fetch_with_redirect_guard
# ---------------------------------------------------------------------------


class TestFetchWithRedirectGuard:
    def test_direct_response(self) -> None:
        resp = MagicMock()
        resp.is_redirect = False
        resp.is_permanent_redirect = False
        resp.status_code = 200

        with patch("solus.modules._helpers.requests.get", return_value=resp):
            result = fetch_with_redirect_guard("http://example.com")
        assert result is resp

    def test_follows_redirect(self) -> None:
        redirect_resp = MagicMock()
        redirect_resp.is_redirect = True
        redirect_resp.is_permanent_redirect = False
        redirect_resp.headers = {"Location": "http://example.com/final"}

        final_resp = MagicMock()
        final_resp.is_redirect = False
        final_resp.is_permanent_redirect = False
        final_resp.status_code = 200

        with patch("solus.modules._helpers.requests.get", side_effect=[redirect_resp, final_resp]):
            result = fetch_with_redirect_guard("http://example.com/start")
        assert result is final_resp

    def test_too_many_redirects(self) -> None:
        redirect_resp = MagicMock()
        redirect_resp.is_redirect = True
        redirect_resp.is_permanent_redirect = False
        redirect_resp.headers = {"Location": "http://example.com/loop"}

        with patch("solus.modules._helpers.requests.get", return_value=redirect_resp):
            with pytest.raises(RuntimeError, match="too many redirects"):
                fetch_with_redirect_guard("http://example.com/start")

    def test_missing_location_header(self) -> None:
        redirect_resp = MagicMock()
        redirect_resp.is_redirect = True
        redirect_resp.is_permanent_redirect = False
        redirect_resp.headers = {}  # No Location

        with patch("solus.modules._helpers.requests.get", return_value=redirect_resp):
            result = fetch_with_redirect_guard("http://example.com")
        # Should return the response (after raise_for_status)
        redirect_resp.raise_for_status.assert_called_once()

    def test_redirect_to_private_blocked(self) -> None:
        redirect_resp = MagicMock()
        redirect_resp.is_redirect = True
        redirect_resp.is_permanent_redirect = False
        redirect_resp.headers = {"Location": "http://127.0.0.1/internal"}

        with patch("solus.modules._helpers.requests.get", return_value=redirect_resp):
            with pytest.raises(RuntimeError, match="private or loopback"):
                fetch_with_redirect_guard("http://example.com", block_private=True)


# ---------------------------------------------------------------------------
# as_bool
# ---------------------------------------------------------------------------


class TestAsBool:
    def test_bool_passthrough(self) -> None:
        assert as_bool(True) is True
        assert as_bool(False) is False

    def test_truthy_strings(self) -> None:
        for val in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON"):
            assert as_bool(val) is True, f"Expected True for {val!r}"

    def test_falsy_strings(self) -> None:
        for val in ("0", "false", "False", "no", "off", "", "anything"):
            assert as_bool(val) is False, f"Expected False for {val!r}"

    def test_whitespace_stripped(self) -> None:
        assert as_bool("  true  ") is True
        assert as_bool("  false  ") is False

    def test_int_coercion(self) -> None:
        assert as_bool(1) is True
        assert as_bool(0) is False
        assert as_bool(42) is True

    def test_none(self) -> None:
        assert as_bool(None) is False


# ---------------------------------------------------------------------------
# runtime_flag / param
# ---------------------------------------------------------------------------


class TestUtilityFunctions:
    def test_runtime_flag_present(self) -> None:
        ctx = MagicMock()
        ctx.data = {"runtime": {"verbose": True}}
        assert runtime_flag(ctx, "verbose", False) is True

    def test_runtime_flag_missing(self) -> None:
        ctx = MagicMock()
        ctx.data = {}
        assert runtime_flag(ctx, "verbose", False) is False

    def test_runtime_flag_non_dict(self) -> None:
        ctx = MagicMock()
        ctx.data = {"runtime": "not-a-dict"}
        assert runtime_flag(ctx, "verbose", False) is False

    def test_param_from_ctx_params(self) -> None:
        ctx = MagicMock()
        ctx.params = {"model": "custom:7b"}
        step = MagicMock()
        step.config = {"model": "default:3b"}
        assert param(ctx, "model", step, "fallback") == "custom:7b"

    def test_param_from_step_config(self) -> None:
        ctx = MagicMock()
        ctx.params = {}
        step = MagicMock()
        step.config = {"model": "default:3b"}
        assert param(ctx, "model", step, "fallback") == "default:3b"

    def test_param_default(self) -> None:
        ctx = MagicMock()
        ctx.params = {}
        step = MagicMock()
        step.config = {}
        assert param(ctx, "model", step, "fallback") == "fallback"

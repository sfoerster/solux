from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

import requests

if TYPE_CHECKING:
    from solux.workflows.models import Context, Step

_log = logging.getLogger(__name__)


def interpolate_env(val: str, strict: bool = False, warn_missing: bool = True) -> str:
    """Replace ``${env:VAR_NAME}`` patterns with environment variable values.

    If *strict* is True, raises ``RuntimeError`` when a referenced variable is
    not set in the environment instead of substituting an empty string.
    """

    def _replace(m: re.Match) -> str:
        var_name = m.group(1)
        value = os.environ.get(var_name)
        if value is None:
            if strict:
                raise RuntimeError(
                    f"Required environment variable '{var_name}' is not set. "
                    "Set it in your environment or disable strict_env_vars in config."
                )
            if warn_missing:
                _log.warning("interpolate_env: environment variable %r is not set", var_name)
            return ""
        return value

    return re.sub(r"\$\{env:([^}]+)\}", _replace, val)


def _is_private_ip(host: str) -> bool:
    """Return True if *host* is a loopback/private/link-local literal or hostname."""
    if host.lower() in ("localhost", "localhost.localdomain"):
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False  # non-IP hostname — DNS not resolved here


def _resolved_ips(hostname: str) -> set[str]:
    results: set[str] = set()
    try:
        addrinfo = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return results
    for item in addrinfo:
        sockaddr = item[4]
        if not sockaddr:
            continue
        ip = sockaddr[0]
        if isinstance(ip, str):
            results.add(ip)
    return results


def validate_http_url(
    url: str,
    context: str = "",
    block_private: bool = False,
    *,
    resolve_hostname: bool = False,
) -> None:
    """Raise RuntimeError if *url* is not an http/https URL.

    If *block_private* is True, also raises for URLs targeting RFC-1918,
    loopback, or link-local addresses (SSRF prevention).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        prefix = f"{context}: " if context else ""
        raise RuntimeError(
            f"{prefix}URL scheme '{parsed.scheme or '(empty)'}' is not allowed; only http and https are permitted"
        )
    if block_private:
        host = parsed.hostname or ""
        prefix = f"{context}: " if context else ""
        _safe_url = f"{parsed.scheme}://[redacted]"
        if _is_private_ip(host):
            raise RuntimeError(
                f"{prefix}URL {_safe_url!r} targets a private or loopback address, which is "
                "not permitted in the current security mode."
            )
        if resolve_hostname and host:
            resolved = _resolved_ips(host)
            if not resolved:
                raise RuntimeError(f"{prefix}URL {_safe_url!r} host could not be resolved safely in untrusted mode")
            for ip in resolved:
                if _is_private_ip(ip):
                    raise RuntimeError(
                        f"{prefix}URL {_safe_url!r} resolved to a private/loopback address, "
                        "which is not permitted in the current security mode."
                    )


_MAX_REDIRECTS = 6


def fetch_with_redirect_guard(
    url: str,
    *,
    context: str = "",
    block_private: bool = False,
    user_agent: str = "solux/0.5.0",
    timeout: int = 30,
) -> requests.Response:
    """GET *url* while validating each redirect hop for SSRF safety.

    Follows up to ``_MAX_REDIRECTS`` redirects manually so that every
    intermediate URL can be checked.  Returns the final
    :class:`requests.Response`.
    """
    current = url
    for _ in range(_MAX_REDIRECTS):
        validate_http_url(
            current,
            context,
            block_private=block_private,
            resolve_hostname=block_private,
        )
        resp = requests.get(
            current,
            timeout=timeout,
            headers={"User-Agent": user_agent},
            allow_redirects=False,
        )
        if getattr(resp, "is_redirect", False) is True or getattr(resp, "is_permanent_redirect", False) is True:
            location = resp.headers.get("Location", "").strip()
            if not location:
                resp.raise_for_status()
                return resp
            current = urljoin(current, location)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"{context + ': ' if context else ''}too many redirects")


def runtime_flag(ctx: "Context", key: str, default: Any) -> Any:
    """Read a value from ``ctx.data["runtime"]``."""
    runtime = ctx.data.get("runtime", {})
    if isinstance(runtime, dict):
        return runtime.get(key, default)
    return default


def param(ctx: "Context", key: str, step: "Step", default: Any) -> Any:
    """Resolve a parameter from context params first, then step config."""
    if key in ctx.params:
        return ctx.params[key]
    return step.config.get(key, default)


def as_bool(value: Any) -> bool:
    """Coerce a value to bool, accepting common truthy strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)

"""Minimal ANSI color helpers for CLI-style output.

Respects ``NO_COLOR`` (https://no-color.org/) and ``FORCE_COLOR`` env vars.
Falls back to plain text when stdout is not a TTY.
"""

from __future__ import annotations

import os
import sys


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    try:
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    except Exception:  # noqa: BLE001
        return False


def _wrap(code: str, text: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return _wrap("32", text)


def red(text: str) -> str:
    return _wrap("31", text)


def yellow(text: str) -> str:
    return _wrap("33", text)


def bold(text: str) -> str:
    return _wrap("1", text)


def dim(text: str) -> str:
    return _wrap("2", text)

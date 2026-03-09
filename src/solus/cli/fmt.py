"""Backward-compatible color helper import path for CLI modules/tests."""

from __future__ import annotations

from ..fmt import _supports_color, bold, dim, green, red, yellow

__all__ = ["_supports_color", "green", "red", "yellow", "bold", "dim"]

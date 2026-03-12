from __future__ import annotations

from solus.cli.fmt import _supports_color, bold, dim, green, red, yellow


def test_no_color_env_disables_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert not _supports_color()
    assert green("ok") == "ok"
    assert red("fail") == "fail"
    assert yellow("warn") == "warn"
    assert bold("b") == "b"
    assert dim("d") == "d"


def test_force_color_enables_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert _supports_color()
    assert green("ok") == "\033[32mok\033[0m"
    assert red("fail") == "\033[31mfail\033[0m"
    assert yellow("warn") == "\033[33mwarn\033[0m"
    assert bold("b") == "\033[1mb\033[0m"
    assert dim("d") == "\033[2md\033[0m"


def test_no_color_takes_precedence_over_force_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert not _supports_color()


def test_non_tty_disables_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    # In pytest, stdout is not a TTY
    assert not _supports_color()
    assert green("ok") == "ok"

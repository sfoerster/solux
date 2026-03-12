from __future__ import annotations

from pathlib import Path

from solus.config import load_config


def test_solus_oidc_env_overrides_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[security]
mode = "trusted"
oidc_issuer = "https://from-config.example/realms/myrealm"
oidc_audience = "from-config"
oidc_require_auth = false
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("SOLUS_OIDC_ISSUER", "https://from-env.example/realms/myrealm")
    monkeypatch.setenv("SOLUS_OIDC_AUDIENCE", "from-env")
    monkeypatch.setenv("SOLUS_OIDC_REQUIRE_AUTH", "true")

    cfg = load_config(config_path)
    assert cfg.security.oidc_issuer == "https://from-env.example/realms/myrealm"
    assert cfg.security.oidc_audience == "from-env"
    assert cfg.security.oidc_require_auth is True


def test_audit_env_overrides_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[audit]
enabled = true
syslog_addr = ""
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("SOLUS_AUDIT_ENABLED", "false")
    monkeypatch.setenv("AUDIT_SYSLOG_ADDR", "udp://siem.internal:514")

    cfg = load_config(config_path)
    assert cfg.audit.enabled is False
    assert cfg.audit.syslog_addr == "udp://siem.internal:514"

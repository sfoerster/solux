"""Tests for the RBAC module (solus.serve.rbac)."""

from __future__ import annotations

import pytest

from solus.serve.rbac import (
    PERMISSIONS,
    check_permission,
    extract_roles,
    highest_role,
)


# ── Permission map structure ────────────────────────────────────────────


class TestPermissionMap:
    def test_admin_has_wildcard(self) -> None:
        assert "*" in PERMISSIONS["admin"]

    def test_three_roles_defined(self) -> None:
        assert set(PERMISSIONS.keys()) == {"admin", "operator", "viewer"}

    def test_operator_cannot_wildcard(self) -> None:
        assert "*" not in PERMISSIONS["operator"]

    def test_viewer_cannot_wildcard(self) -> None:
        assert "*" not in PERMISSIONS["viewer"]

    def test_viewer_subset_of_operator(self) -> None:
        # Every viewer permission should also be an operator permission
        assert PERMISSIONS["viewer"].issubset(PERMISSIONS["operator"])

    def test_operator_has_write_permissions(self) -> None:
        write_perms = {
            "workflows.create",
            "workflows.run",
            "workflows.delete",
            "triggers.create",
            "triggers.toggle",
            "triggers.run",
            "jobs.retry",
            "jobs.clear",
            "worker.start",
            "worker.stop",
        }
        for perm in write_perms:
            assert perm in PERMISSIONS["operator"], f"operator missing {perm}"

    def test_viewer_lacks_write_permissions(self) -> None:
        write_perms = {
            "workflows.create",
            "workflows.run",
            "workflows.delete",
            "triggers.create",
            "triggers.toggle",
            "triggers.run",
            "jobs.retry",
            "jobs.clear",
            "worker.start",
            "worker.stop",
        }
        for perm in write_perms:
            assert perm not in PERMISSIONS["viewer"], f"viewer should not have {perm}"


# ── extract_roles ────────────────────────────────────────────────────────


class TestExtractRoles:
    def test_keycloak_realm_access(self) -> None:
        claims = {"realm_access": {"roles": ["admin", "uma_authorization"]}}
        roles = extract_roles(claims)
        assert roles == ["admin"]

    def test_keycloak_multiple_roles(self) -> None:
        claims = {"realm_access": {"roles": ["operator", "viewer"]}}
        roles = extract_roles(claims)
        assert set(roles) == {"operator", "viewer"}

    def test_empty_roles_defaults_to_viewer(self) -> None:
        claims = {"realm_access": {"roles": []}}
        roles = extract_roles(claims)
        assert roles == ["viewer"]

    def test_no_realm_access_defaults_to_viewer(self) -> None:
        claims = {"sub": "user123"}
        roles = extract_roles(claims)
        assert roles == ["viewer"]

    def test_empty_claims_defaults_to_viewer(self) -> None:
        roles = extract_roles({})
        assert roles == ["viewer"]

    def test_unknown_roles_filtered_out(self) -> None:
        claims = {"realm_access": {"roles": ["superuser", "root"]}}
        roles = extract_roles(claims)
        assert roles == ["viewer"]

    def test_custom_claim_path_groups(self) -> None:
        claims = {"groups": ["admin", "users"]}
        roles = extract_roles(claims, role_claim="groups")
        assert roles == ["admin"]

    def test_custom_claim_path_flat_roles(self) -> None:
        claims = {"roles": ["operator"]}
        roles = extract_roles(claims, role_claim="roles")
        assert roles == ["operator"]

    def test_custom_claim_path_nested(self) -> None:
        claims = {"custom": {"nested": {"roles": ["admin"]}}}
        roles = extract_roles(claims, role_claim="custom.nested.roles")
        assert roles == ["admin"]

    def test_fallback_to_alternative_claim_paths(self) -> None:
        # Primary claim path doesn't exist, but fallback "roles" does
        claims = {"roles": ["operator"]}
        roles = extract_roles(claims, role_claim="nonexistent.path")
        assert roles == ["operator"]

    def test_fallback_to_realm_access(self) -> None:
        # Primary claim path doesn't exist, but realm_access.roles does
        claims = {"realm_access": {"roles": ["admin"]}}
        roles = extract_roles(claims, role_claim="custom.path")
        assert roles == ["admin"]

    def test_non_list_value_ignored(self) -> None:
        claims = {"realm_access": {"roles": "admin"}}
        roles = extract_roles(claims)
        assert roles == ["viewer"]

    def test_non_dict_claim_ignored(self) -> None:
        claims = {"realm_access": "not_a_dict"}
        roles = extract_roles(claims)
        assert roles == ["viewer"]

    def test_mixed_known_unknown_roles(self) -> None:
        claims = {"realm_access": {"roles": ["admin", "unknown", "viewer", "superuser"]}}
        roles = extract_roles(claims)
        assert set(roles) == {"admin", "viewer"}

    def test_all_three_roles(self) -> None:
        claims = {"realm_access": {"roles": ["admin", "operator", "viewer"]}}
        roles = extract_roles(claims)
        assert set(roles) == {"admin", "operator", "viewer"}


# ── check_permission ─────────────────────────────────────────────────────


class TestCheckPermission:
    def test_admin_can_do_anything(self) -> None:
        assert check_permission(["admin"], "workflows.create") is True
        assert check_permission(["admin"], "config.save") is True
        assert check_permission(["admin"], "anything.at.all") is True

    def test_operator_can_run_workflows(self) -> None:
        assert check_permission(["operator"], "workflows.run") is True

    def test_operator_can_list_workflows(self) -> None:
        assert check_permission(["operator"], "workflows.list") is True

    def test_operator_cannot_save_config(self) -> None:
        # config.save is admin-only (not in operator perms, not wildcard)
        assert check_permission(["operator"], "config.save") is False

    def test_viewer_can_list_workflows(self) -> None:
        assert check_permission(["viewer"], "workflows.list") is True

    def test_viewer_cannot_run_workflows(self) -> None:
        assert check_permission(["viewer"], "workflows.run") is False

    def test_viewer_cannot_delete(self) -> None:
        assert check_permission(["viewer"], "workflows.delete") is False
        assert check_permission(["viewer"], "jobs.delete") is False

    def test_empty_roles_denies(self) -> None:
        assert check_permission([], "workflows.list") is False

    def test_unknown_role_denies(self) -> None:
        assert check_permission(["superuser"], "workflows.list") is False

    def test_multiple_roles_highest_wins(self) -> None:
        # If one role has the perm, it's allowed
        assert check_permission(["viewer", "operator"], "workflows.run") is True

    def test_admin_plus_viewer(self) -> None:
        assert check_permission(["viewer", "admin"], "config.save") is True

    def test_viewer_can_read_audit(self) -> None:
        assert check_permission(["viewer"], "audit.read") is True

    def test_viewer_can_read_dashboard(self) -> None:
        assert check_permission(["viewer"], "dashboard.read") is True

    def test_operator_can_manage_worker(self) -> None:
        assert check_permission(["operator"], "worker.start") is True
        assert check_permission(["operator"], "worker.stop") is True
        assert check_permission(["operator"], "worker.restart") is True

    def test_viewer_cannot_manage_worker(self) -> None:
        assert check_permission(["viewer"], "worker.start") is False
        assert check_permission(["viewer"], "worker.stop") is False


# ── highest_role ─────────────────────────────────────────────────────────


class TestHighestRole:
    def test_admin_is_highest(self) -> None:
        assert highest_role(["admin", "operator", "viewer"]) == "admin"

    def test_operator_over_viewer(self) -> None:
        assert highest_role(["viewer", "operator"]) == "operator"

    def test_single_viewer(self) -> None:
        assert highest_role(["viewer"]) == "viewer"

    def test_single_admin(self) -> None:
        assert highest_role(["admin"]) == "admin"

    def test_empty_defaults_to_viewer(self) -> None:
        assert highest_role([]) == "viewer"

    def test_unknown_roles_default_to_viewer(self) -> None:
        assert highest_role(["superuser", "root"]) == "viewer"

    def test_mixed_known_unknown(self) -> None:
        assert highest_role(["unknown", "operator", "irrelevant"]) == "operator"

    def test_order_independent(self) -> None:
        assert highest_role(["operator", "admin"]) == "admin"
        assert highest_role(["admin", "operator"]) == "admin"

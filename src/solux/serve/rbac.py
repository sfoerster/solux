"""Role-Based Access Control for Solux API.

Three roles with hierarchical permissions:
- admin: wildcard access
- operator: run/create workflows, manage triggers/jobs, read audit
- viewer: read-only access
"""

from __future__ import annotations

from typing import Any

# Permission map: role -> set of allowed permission strings
PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"*"}),
    "operator": frozenset(
        {
            "workflows.list",
            "workflows.create",
            "workflows.run",
            "workflows.delete",
            "triggers.list",
            "triggers.create",
            "triggers.toggle",
            "triggers.run",
            "triggers.delete",
            "jobs.list",
            "jobs.retry",
            "jobs.delete",
            "jobs.clear",
            "worker.start",
            "worker.stop",
            "worker.restart",
            "worker.status",
            "audit.read",
            "sources.list",
            "sources.ingest",
            "modules.list",
            "examples.list",
            "config.read",
            "dashboard.read",
        }
    ),
    "viewer": frozenset(
        {
            "workflows.list",
            "triggers.list",
            "jobs.list",
            "sources.list",
            "worker.status",
            "modules.list",
            "examples.list",
            "config.read",
            "dashboard.read",
            "audit.read",
        }
    ),
}

# Priority order for role hierarchy (highest first)
_ROLE_PRIORITY = ("admin", "operator", "viewer")


def extract_roles(claims: dict[str, Any], role_claim: str = "realm_access.roles") -> list[str]:
    """Extract known roles from JWT claims.

    Supports dotted claim paths (e.g. ``realm_access.roles`` for Keycloak,
    ``groups`` for Okta, ``roles`` for Entra ID).

    Returns a list of recognized roles, defaulting to ``["viewer"]`` if none found.
    """
    parts = role_claim.split(".")
    value: Any = claims
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if not isinstance(value, (list, tuple)):
        # Fallback: try common alternative claim locations
        for alt in ("realm_access.roles", "roles", "groups"):
            if alt == role_claim:
                continue
            alt_parts = alt.split(".")
            alt_value: Any = claims
            for p in alt_parts:
                if isinstance(alt_value, dict):
                    alt_value = alt_value.get(p)
                else:
                    alt_value = None
                    break
            if isinstance(alt_value, (list, tuple)):
                value = alt_value
                break

    if not isinstance(value, (list, tuple)):
        return ["viewer"]

    known = set(PERMISSIONS.keys())
    roles = [str(r) for r in value if str(r) in known]
    return roles if roles else ["viewer"]


def check_permission(roles: list[str], permission: str) -> bool:
    """Check if any of the given roles grant the specified permission."""
    for role in roles:
        perms = PERMISSIONS.get(role, frozenset())
        if "*" in perms or permission in perms:
            return True
    return False


def highest_role(roles: list[str]) -> str:
    """Return the highest-priority role from the list."""
    for role in _ROLE_PRIORITY:
        if role in roles:
            return role
    return "viewer"

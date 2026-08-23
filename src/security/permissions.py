"""Centralized permission checks and tool audit logging."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.security.auth import User, validate_user

LOGGER = logging.getLogger("parcelpilot.audit")
PERMISSIONS = frozenset(
    {
        "search_documents",
        "lookup_account",
        "lookup_order",
        "lookup_ticket",
        "create_escalation",
        "scan_operational_issues",
    }
)


class AuthorizationError(PermissionError):
    """Controlled error raised when a user lacks a tool permission."""


def audit_tool_call(user: User, permission: str, tool_name: str, allowed: bool) -> None:
    """Write a secret-free, structured audit event to the application logger."""
    LOGGER.info(
        "tool_authorization user_id=%s role=%s permission=%s tool=%s allowed=%s timestamp=%s",
        user.user_id,
        user.role,
        permission,
        tool_name,
        allowed,
        datetime.now(timezone.utc).isoformat(),
    )


def check_permission(user: User | None, permission: str, tool_name: str | None = None) -> User:
    """Validate identity and enforce an explicit permission before tool access."""
    validated_user = validate_user(user)
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission '{permission}'.")

    allowed = permission in validated_user.permissions
    audit_tool_call(validated_user, permission, tool_name or permission, allowed)
    if not allowed:
        raise AuthorizationError(
            f"Access denied: role '{validated_user.role}' lacks permission '{permission}'."
        )
    return validated_user

"""Mock internal identities for tool authorization."""

from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """A validated internal user identity; this is not an authentication system."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    role: str
    permissions: frozenset[str] = Field(default_factory=frozenset)
    access_scope: str = "global"


MOCK_USERS = {
    "support_agent": User(
        user_id="support_agent",
        role="support_agent",
        permissions=frozenset({"search_documents", "lookup_account", "lookup_order", "lookup_ticket", "scan_operational_issues"}),
    ),
    "support_manager": User(
        user_id="support_manager",
        role="support_manager",
        permissions=frozenset(
            {"search_documents", "lookup_account", "lookup_order", "lookup_ticket", "create_escalation", "scan_operational_issues"}
        ),
    ),
    "admin": User(
        user_id="admin",
        role="admin",
        permissions=frozenset(
            {"search_documents", "lookup_account", "lookup_order", "lookup_ticket", "create_escalation", "scan_operational_issues"}
        ),
    ),
}


def get_mock_user(user_id: str) -> User | None:
    """Return a copy of a known mock identity, or None for an unknown identity."""
    return MOCK_USERS.get(user_id)


def validate_user(user: User | None) -> User:
    """Validate an explicit user, retaining trusted compatibility for legacy calls."""
    if user is None:
        return MOCK_USERS["support_manager"]
    if not isinstance(user, User) or not user.user_id.strip() or not user.role.strip():
        raise ValueError("A valid User instance is required.")
    return user

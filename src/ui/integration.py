"""UI integration helpers that keep Streamlit separate from application logic."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.agent.confirmation import confirm_action, reject_action, request_confirmation
from src.agent.graph import normalize_response_text, run_investigation
from src.agent.state import PendingAction
from src.tools.monitoring import scan_operational_issues
from src.security.auth import MOCK_USERS, User


def available_users() -> list[User]:
    """Return the fixed mock identities available to the UI."""
    return list(MOCK_USERS.values())


def get_user(user_id: str) -> User | None:
    """Resolve a sidebar selection through the existing auth module."""
    return MOCK_USERS.get(user_id)


def start_investigation(question: str, user: User, model: Any | None = None) -> dict[str, Any]:
    """Run the authenticated agent and return only UI-safe state fields."""
    try:
        state = run_investigation(question, user, model=model)
    except Exception as exc:
        return {"error": str(exc)}

    return {
        "final_answer": normalize_response_text(state.get("final_answer", "No answer was produced.")),
        "sources": state.get("sources", []),
        "tool_results": state.get("tool_results", []),
        "pending_action": state.get("pending_action"),
        "confirmation_required": state.get("confirmation_required", False),
        "confirmation_id": state.get("confirmation_id"),
        "confirmation_status": state.get("confirmation_status", ""),
    }


def scan_issues(user: User, db_path: str | None = None) -> list[dict[str, Any]] | dict[str, str]:
    """Run the authorized read-only issue detector for the UI."""
    return scan_operational_issues(user=user, db_path=db_path)


def prepare_issue_escalation(issue: dict[str, Any], user: User) -> dict[str, Any]:
    """Register a ticket-backed recommendation for explicit confirmation."""
    if issue.get("recommended_action") != "create_escalation" or not issue.get("ticket_id"):
        return {"error": "Only ticket-backed escalation recommendations can be prepared."}
    pending_action = PendingAction(
        action="create_escalation",
        ticket_id=issue["ticket_id"],
        reason=issue.get("description", issue.get("title", "Operational issue detected")),
        priority=issue.get("severity", "medium"),
        requested_by=user.user_id,
        created_at=datetime.now(timezone.utc),
    )
    return request_confirmation(pending_action, user)


def confirm_pending(confirmation_id: str, user: User, db_path: str | None = None) -> dict[str, Any]:
    """Confirm through the Phase 8 API; never call the action tool directly."""
    try:
        return confirm_action(confirmation_id, user, db_path)
    except Exception as exc:
        return {"error": "confirmation_failed", "message": str(exc)}


def reject_pending(confirmation_id: str, user: User) -> dict[str, Any]:
    """Reject through the Phase 8 API without touching application data directly."""
    try:
        return reject_action(confirmation_id, user)
    except Exception as exc:
        return {"error": "rejection_failed", "message": str(exc)}


def confirmation_details(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return display-ready pending-action fields, or None when no confirmation is active."""
    if not state.get("confirmation_required") or state.get("confirmation_status") != "pending":
        return None
    pending = state.get("pending_action")
    if pending is None:
        return None
    details = pending.model_dump() if hasattr(pending, "model_dump") else dict(pending)
    details["confirmation_id"] = state.get("confirmation_id")
    return details


def user_changed(previous_user_id: str, current_user_id: str) -> bool:
    """Identify a user switch so the UI can clear stale workflow state."""
    return previous_user_id != current_user_id
